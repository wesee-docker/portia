import Ember from 'ember';

export default Ember.Component.extend({
    classNames: ['list-item-selectable'],
    classNameBindings: ['selecting'],

    model: null,
    change: null,
    choices: [],
    buttonClass: null,
    menuAlign: 'left',
    menuClass: null,
    menuContainer: null,

    selecting: false,
    value: null,

    actions: {
        startSelecting() {
            if (!this.get('model.isDeleted')) {
                this.set('selecting', true);
            }
        }
    }
});
