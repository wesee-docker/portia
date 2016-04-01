import IconButton from './icon-button';

export default IconButton.extend({
    classNames: ['list-item-icon'],
    classNameBindings: ['model.isDeleted:disabled'],

    model: null,

    click() {
        if (!this.get('model.isDeleted')) {
            return this._super(...arguments);
        }
    }
});
