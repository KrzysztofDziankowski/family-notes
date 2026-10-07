// Type changes explain the selected date without overwriting its value.
(() => {
    const labels = {
        note: 'Data zapisania',
        calendar_event: 'Data wydarzenia',
        todo: 'Termin wykonania',
    };
    const initialize = () => {
        document.querySelectorAll('[data-entry-date-type]').forEach((type) => {
            const date = type.form?.querySelector(`[name="${type.name.replace(/entry_type$/, 'date')}"]`);
            if (!date) return;
            const label = type.form.querySelector(`label[for="${date.id}"]`);
            if (!label) return;
            type.addEventListener('change', () => {
                const attribute = `data-entry-date-label-${type.value.replaceAll('_', '-')}`;
                label.textContent = type.getAttribute(attribute) || labels[type.value] || labels.note;
            });
        });
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, {once: true});
    } else {
        initialize();
    }
})();
