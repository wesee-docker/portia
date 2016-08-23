from collections import OrderedDict

import requests

from rest_framework.decorators import detail_route
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK

from django.conf import settings

from .projects import BaseProjectModelRoute, ProjectDownloadMixin
from ..jsonapi.exceptions import JsonApiGeneralException
from portia_orm.models import Spider


class SpiderRoute(ProjectDownloadMixin, BaseProjectModelRoute):
    lookup_url_kwarg = 'spider_id'
    lookup_value_regex = '[^/]+'
    default_model = Spider

    def get_instance(self):
        return self.get_collection()[self.kwargs.get('spider_id')]

    def get_collection(self):
        return self.project.spiders

    @detail_route(methods=['post'])
    def schedule(self):
        schedule_data = self._schedule_data()
        request = requests.post(settings.SCHEDULE_URL, data=schedule_data)
        if request.status_code != 200:
            return JsonApiGeneralException(
                request.status_code, request.content)
        response = self.retrieve()
        data = OrderedDict()
        data.update(response.data)
        data.setdefault('meta', {})['scheduled'] = True
        return Response(data, status=HTTP_200_OK)

    def _schedule_data(self, spider, args):
        data = {
            'project': self.project.id,
            'spider': self.spider.id
        }
        if self.storage.version_control:
            branch = self.query.get('branch', None)
            commit = self.query.get('commit_id', None)
            if not branch and self.storage.repo.has_branch(self.user):
                branch = self.user
            storage = self.storage.__class__(
                self.storage.name, self.storage.author, commit, branch)
            commit_id = storage._commit.id
            data['version'] = commit_id
        return data
