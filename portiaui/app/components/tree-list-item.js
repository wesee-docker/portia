import Ember from 'ember';
import AnimationContainer from './animation-container';

export default AnimationContainer.extend({
    tagName: 'li',
    classNames: ['tree-list-item'],
    classNameBindings: ['modelDeleted'],

    model: null,
    setWidth: false,
    hasChildren: false,

    modelDeleted: Ember.computed.readOnly('model.isDeleted')
});
