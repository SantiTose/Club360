// Main JavaScript file for Club 360

// Close alerts after 5 seconds
window.addEventListener('load', function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.display = 'none';
        }, 5000);
    });
});

window.addEventListener('DOMContentLoaded', function() {
    const modal = document.getElementById('confirm-modal');
    if (!modal) return;

    const titleEl = document.getElementById('confirm-modal-title');
    const messageEl = document.getElementById('confirm-modal-message');
    const acceptBtn = document.getElementById('confirm-modal-accept');
    const cancelBtn = document.getElementById('confirm-modal-cancel');

    let pendingAction = null;
    let pendingTrigger = null;

    function openModal({ title, message, actionLabel = 'Confirmar', actionClass = 'btn-danger' }) {
        titleEl.textContent = title;
        messageEl.textContent = message;
        acceptBtn.textContent = actionLabel;
        acceptBtn.className = `btn ${actionClass}`;
        modal.classList.add('is-open');
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
        cancelBtn.focus();
    }

    function closeModal() {
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('modal-open');
        pendingAction = null;
        if (pendingTrigger) {
            pendingTrigger.focus();
            pendingTrigger = null;
        }
    }

    function confirmElement(el) {
        pendingTrigger = el;
        pendingAction = function() {
            if (el.tagName === 'A' && el.href) {
                window.location.href = el.href;
                return;
            }

            if (el.tagName === 'FORM') {
                el.submit();
                return;
            }

            const form = el.closest('form');
            if (form) {
                form.submit();
            }
        };

        openModal({
            title: el.dataset.confirmTitle || 'Confirmar acción',
            message: el.dataset.confirmMessage || '¿Querés continuar con esta acción?',
            actionLabel: el.dataset.confirmAction || 'Confirmar',
            actionClass: el.dataset.confirmVariant === 'secondary' ? 'btn-primary' : 'btn-danger'
        });
    }

    function showNotice({ title, message }) {
        pendingTrigger = document.activeElement;
        pendingAction = closeModal;
        openModal({
            title,
            message,
            actionLabel: 'Entendido',
            actionClass: 'btn-primary'
        });
    }

    document.addEventListener('click', function(event) {
        const trigger = event.target.closest('[data-confirm="true"]');
        if (!trigger) return;

        if (trigger.tagName === 'A') {
            event.preventDefault();
            confirmElement(trigger);
            return;
        }

        if (trigger.tagName === 'BUTTON') {
            event.preventDefault();
            confirmElement(trigger);
        }
    });

    document.addEventListener('submit', function(event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (form.dataset.confirm !== 'true') return;
        if (form.dataset.confirmed === 'true') {
            form.dataset.confirmed = 'false';
            return;
        }

        event.preventDefault();
        pendingTrigger = form.querySelector('[type="submit"]') || form;
        pendingAction = function() {
            form.dataset.confirmed = 'true';
            form.submit();
        };
        openModal({
            title: form.dataset.confirmTitle || 'Confirmar acción',
            message: form.dataset.confirmMessage || '¿Querés continuar con esta acción?',
            actionLabel: form.dataset.confirmAction || 'Confirmar',
            actionClass: form.dataset.confirmVariant === 'secondary' ? 'btn-primary' : 'btn-danger'
        });
    });

    modal.addEventListener('click', function(event) {
        if (event.target.hasAttribute('data-confirm-close')) {
            closeModal();
        }
    });

    cancelBtn.addEventListener('click', closeModal);
    acceptBtn.addEventListener('click', function() {
        const action = pendingAction;
        closeModal();
        if (action) action();
    });

    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && modal.classList.contains('is-open')) {
            closeModal();
        }
    });

    window.Club360Dialogs = {
        showNotice
    };
});
