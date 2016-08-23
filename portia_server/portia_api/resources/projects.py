from collections import OrderedDict, defaultdict
from itertools import chain

from django.utils.functional import cached_property
from rest_framework.decorators import detail_route
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from six import iteritems

from portia_orm.models import Project
from storage import get_storage_class
from .route import (JsonApiRoute, JsonApiModelRoute,
                    ListModelMixin, RetrieveModelMixin)
from .response import FileResponse
from ..jsonapi.exceptions import (JsonApiFeatureNotAvailableError,
                                  JsonApiBadRequestError,
                                  JsonApiNotFoundError,
                                  JsonApiConflictError)
from ..utils.download import ProjectArchiver, CodeProjectArchiver


class ProjectDownloadMixin(object):
    @detail_route(methods=['get'])
    def download(self, *args, **kwargs):
        fmt = self.query.get('format', 'spec')
        version = self.query.get('version', None)
        branch = self.query.get('branch', None)
        spider_id = self.kwargs.get('spider_id', None)
        spiders = [spider_id] if spider_id is not None else None
        if self.storage.version_control and (version or branch):
            storage = self.storage.__class__(
                self.storage.name, self.storage.author, version, branch)
        else:
            storage = self.storage
        archiver = CodeProjectArchiver if fmt == u'code' else ProjectArchiver
        content = archiver(storage).archive(spiders)
        return FileResponse('{}.zip'.format(storage.name), content,
                            status=HTTP_200_OK)


class BaseProjectRoute(JsonApiRoute):
    @cached_property
    def projects(self):
        storage_class = get_storage_class()
        return storage_class.get_projects(self.request.user)

    @cached_property
    def project(self):
        project_id = self.kwargs.get('project_id')
        name = self.projects[project_id]
        return Project(self.storage, id=project_id, name=name)


class BaseProjectModelRoute(BaseProjectRoute, JsonApiModelRoute):
    pass


class ProjectRoute(ProjectDownloadMixin, BaseProjectRoute,
                   ListModelMixin, RetrieveModelMixin):
    lookup_url_kwarg = 'project_id'
    default_model = Project

    class FakeStorage(object):
        def exists(self, *args, **kwargs):
            return False

        def listdir(self, *args, **kwargs):
            return [], []

    def create(self):
        """Create a new project from the provided attributes"""
        try:
            name = self.data['name']
        except KeyError:
            return JsonApiBadRequestError('No `name` provided')

        if not self.storage.is_valid_filename(name):
            return JsonApiBadRequestError(
                '"{}" is not a valid project name'.format(name))

        # Bootstrap project
        self.kwargs['project_id'] = name
        storage = self.storage
        storage.commit()

        serializer = self.get_serializer(data=self.data, storage=storage,
                                         partial={'id'})
        data = serializer.data
        headers = self.get_success_headers(data)
        return Response(data, status=HTTP_201_CREATED, headers=headers)

    # def update(self):
    #     """Update an exiting project with the provided attributes"""

    # def destroy(self):
    #     """Delete the requested project"""

    @detail_route(methods=['get'])
    def status(self, *args, **kwargs):
        response = self.retrieve()
        data = OrderedDict()
        data.update({
            'meta': {
                'changes': self.get_project_changes()
            }
        })
        data.update(response.data)
        return Response(data, status=HTTP_200_OK)

    @detail_route(methods=['put', 'patch', 'post'])
    def publish(self, *args, **kwargs):
        if not self.storage.version_control and hasattr(self.storage, 'repo'):
            raise JsonApiFeatureNotAvailableError()

        if not self.get_project_changes():
            raise JsonApiBadRequestError('You have no changes to publish')

        force = self.query.get('force', False)
        branch = self.storage.branch
        published = self.storage.repo.publish_branch(branch, force=force)
        if not published:
            return JsonApiConflictError(
                'A conflict occurred when publishing your changes.'
                'You must resolve the conflict before the project can be '
                'published.')
        self.deploy()
        self.storage.repo.delete_branch(branch)
        response = self.retrieve()
        return Response(response.data, status=HTTP_200_OK)

    @detail_route(methods=['put', 'patch', 'post'])
    def reset(self, *args, **kwargs):
        if not self.storage.version_control and hasattr(self.storage, 'repo'):
            raise JsonApiFeatureNotAvailableError()
        branch = self.storage.branch
        master = self.storage.repo.refs['refs/heads/master']
        self.storage.repo.refs['refs/heads/%s' % branch] = master
        return self.retrieve()

    @detail_route(methods=['post'])
    def copy(self, *args, **kwargs):
        from_project_id = self.query.get('from')
        if not from_project_id:
            return JsonApiBadRequestError('`from` parameter must be provided.')
        try:
            self.projects[from_project_id]
        except KeyError:
            return JsonApiNotFoundError(
                'No project exists with the id "{}"'.format(from_project_id))
        models = self.data.get('data', [])
        if not models:
            return JsonApiBadRequestError('No models provided to copy.')
        project, storage = self.project, self.storage
        from_storage = storage.__class__(from_project_id,
                                         author=storage.author)
        from_project = Project(from_storage, id=from_project_id,
                               name=from_project_id)
        instances = defaultdict(list)
        errors = []
        for model_meta in models:
            _id, model_type = model_meta['id'], model_meta['type']
            collection = getattr(from_project, model_type, {})
            try:
                instance = collection[_id]
                instances[model_type].append(instance)
            except KeyError:
                errors.append(_id)
        if errors:
            return JsonApiBadRequestError(
                'Could not find the following ids "{}" in the project.'.format(
                    '", "'.join(errors)))

        # Load schemas and extractors
        from_project.extractors
        from_project.schemas

        to_save = []
        for spider in instances.get('spiders', []):
            to_save.append(spider)
            for sample in spider.samples:
                sample = sample.with_snapshots()
                for item in sample.items:
                    project.schemas.add(item.schema)
                    for annotation in item.annotations:
                        for extractor in annotation.extractors:
                            project.extractors.add(extractor)
                to_save.append(sample)
        for schema in instances.get('schemas', []):
            project.schemas.add(schema).save()
        returned_models = []
        for model in chain(to_save, project.extractors, project.schemas):
            model.storage = storage
            try:
                model.project = project
            except TypeError:
                # Force save any samples as they don't have any staged changes
                model.save(force=True)
            else:
                model.save()
                returned_models.append(model)
        storage.commit()

        # Return new models
        included = []
        for model in returned_models:
            serializer = self.get_serializer(model, storage=storage)
            data = serializer.data
            included.append(data['data'])
            included.extend(data.get('included', []))
        data = OrderedDict(included=included)
        return Response(data, status=HTTP_201_CREATED)

    def get_instance(self):
        return self.project

    def get_collection(self):
        storage = self.FakeStorage()
        return Project.collection(
            Project(storage, id=project_id, name=name)
            for project_id, name in iteritems(self.projects))

    def get_detail_kwargs(self):
        return {
            'include_data': [
                'spiders',
                'schemas',
            ],
            'fields_map': {
                'spiders': [
                    'project',
                ],
                'schemas': [
                    'name',
                    'project',
                ],
            },
            'exclude_map': {
                'projects': [
                    'extractors',
                ],
            }
        }

    def get_list_kwargs(self):
        return {
            'fields_map': {
                'projects': [
                    'name',
                ],
            }
        }

    def get_project_changes(self):
        storage = self.storage
        if not storage.version_control:
            raise JsonApiFeatureNotAvailableError()
        return [{'type': type_, 'path': path, 'old_path': old_path}
                for type_, path, old_path
                in storage.changed_files()]

    def deploy(self):
        pass
