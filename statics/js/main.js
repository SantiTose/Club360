function club360EscapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function club360ToDateKey(value) {
    const date = value instanceof Date ? value : new Date(value);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function club360FormatTime(value) {
    return new Date(value).toLocaleTimeString('es-AR', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
}

function club360FormatLongDate(value) {
    return new Date(`${value}T12:00:00`).toLocaleDateString('es-AR', {
        weekday: 'long',
        day: 'numeric',
        month: 'long'
    });
}

function club360FormatMonthYear(value) {
    return value.toLocaleDateString('es-AR', {
        month: 'long',
        year: 'numeric'
    });
}

function club360GetHourRange(start, end) {
    return `${club360FormatTime(start)} - ${club360FormatTime(end)}`;
}

window.Club360CalendarUI = {
    createMonthAgenda(config) {
        const calendarEl = document.getElementById(config.calendarId);
        const agendaEl = document.getElementById(config.agendaBodyId);
        const agendaTitleEl = document.getElementById(config.agendaTitleId);
        const detailEl = document.getElementById(config.detailBodyId);

        if (!calendarEl || !agendaEl || !agendaTitleEl || !detailEl) return;

        const helpers = {
            escapeHtml: club360EscapeHtml,
            formatTime: club360FormatTime,
            formatLongDate: club360FormatLongDate,
            getHourRange: club360GetHourRange
        };

        const state = {
            events: [],
            selectedDate: null,
            selectedEventId: null,
            currentMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1)
        };

        function startOfMonth(date) {
            return new Date(date.getFullYear(), date.getMonth(), 1);
        }

        function isSameMonth(a, b) {
            return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth();
        }

        function eventDateKey(event) {
            return club360ToDateKey(event.start);
        }

        function groupedEvents() {
            return state.events.reduce((acc, event) => {
                const key = eventDateKey(event);
                acc[key] = acc[key] || [];
                acc[key].push(event);
                return acc;
            }, {});
        }

        function sortedDayEvents() {
            return state.events
                .filter(event => eventDateKey(event) === state.selectedDate)
                .sort((a, b) => new Date(a.start) - new Date(b.start));
        }

        function updateSelectedDayStyle() {
            calendarEl.querySelectorAll('[data-calendar-date]').forEach(cell => {
                cell.classList.toggle('is-selected-day', cell.dataset.calendarDate === state.selectedDate);
            });
        }

        function renderDetail() {
            if (!state.selectedDate) {
                detailEl.innerHTML = config.initialDetailHtml;
                return;
            }

            const event = sortedDayEvents().find(item => String(item.id) === String(state.selectedEventId));
            if (!event) {
                detailEl.innerHTML = config.emptyDetailHtml || config.initialDetailHtml;
                return;
            }

            detailEl.innerHTML = config.renderDetail(event, helpers);
        }

        function renderAgenda() {
            if (!state.selectedDate) {
                agendaTitleEl.textContent = 'Seleccioná un día';
                agendaEl.innerHTML = config.initialAgendaHtml;
                renderDetail();
                return;
            }

            agendaTitleEl.textContent = club360FormatLongDate(state.selectedDate);
            const events = sortedDayEvents();

            if (!events.length) {
                agendaEl.innerHTML = config.emptyAgendaHtml;
                renderDetail();
                return;
            }

            const startHour = config.startHour ?? 8;
            const endHour = config.endHour ?? 22;
            const slotRows = [];

            for (let hour = startHour; hour < endHour; hour += 1) {
                const slotEvents = events.filter(event => new Date(event.start).getHours() === hour);
                const content = slotEvents.length
                    ? slotEvents.map(event => config.renderAgendaCard(event, {
                        isActive: String(event.id) === String(state.selectedEventId),
                        helpers
                    })).join('')
                    : '<div class="calendar-slot-empty">Sin turnos en esta franja</div>';

                slotRows.push(`
                    <div class="calendar-day-slot">
                        <div class="calendar-slot-hour">${String(hour).padStart(2, '0')}:00</div>
                        <div class="calendar-slot-events">${content}</div>
                    </div>
                `);
            }

            agendaEl.innerHTML = slotRows.join('');

            agendaEl.querySelectorAll('[data-event-id]').forEach(button => {
                button.addEventListener('click', function() {
                    state.selectedEventId = button.dataset.eventId;
                    renderAgenda();
                    renderDetail();
                });
            });

            renderDetail();
        }

        function setSelectedDate(dateStr, eventId = null) {
            state.selectedDate = dateStr;
            state.selectedEventId = eventId;
            updateSelectedDayStyle();
            renderAgenda();
        }

        function renderCalendarError(title, message) {
            calendarEl.innerHTML = `
                <div class="calendar-surface-empty">
                    <div class="calendar-surface-empty-badge">Error</div>
                    <h3>${club360EscapeHtml(title)}</h3>
                    <p>${club360EscapeHtml(message)}</p>
                </div>
            `;
        }

        function renderCalendar() {
            const monthStart = startOfMonth(state.currentMonth);
            const firstDay = new Date(monthStart);
            const startWeekDay = (firstDay.getDay() + 6) % 7;
            const daysInMonth = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0).getDate();
            const prevMonthDays = new Date(monthStart.getFullYear(), monthStart.getMonth(), 0).getDate();
            const todayKey = club360ToDateKey(new Date());
            const eventsByDate = groupedEvents();
            const weekdayLabels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
            const dayCells = [];

            for (let i = 0; i < startWeekDay; i += 1) {
                const day = prevMonthDays - startWeekDay + i + 1;
                dayCells.push(`
                    <div class="calendar-month-cell is-outside-month" aria-hidden="true">
                        <div class="calendar-month-cell-top">
                            <span class="calendar-month-day-number">${day}</span>
                        </div>
                        <div class="calendar-month-preview">
                            <span class="calendar-month-preview-empty">Sin turnos</span>
                        </div>
                    </div>
                `);
            }

            for (let day = 1; day <= daysInMonth; day += 1) {
                const date = new Date(monthStart.getFullYear(), monthStart.getMonth(), day);
                const dateKey = club360ToDateKey(date);
                const dayEvents = eventsByDate[dateKey] || [];
                const preview = dayEvents.slice(0, 2).map(event => `
                    <div class="calendar-month-preview-item">${club360EscapeHtml(club360FormatTime(event.start))} · ${club360EscapeHtml(event.title)}</div>
                `).join('');

                dayCells.push(`
                    <button type="button" class="calendar-month-cell ${dateKey === todayKey ? 'is-today' : ''}" data-calendar-date="${dateKey}">
                        <div class="calendar-month-cell-top">
                            <span class="calendar-month-day-number">${day}</span>
                            ${dayEvents.length ? `<span class="calendar-month-day-count">${dayEvents.length}</span>` : ''}
                        </div>
                        <div class="calendar-month-preview">
                            ${preview || '<span class="calendar-month-preview-empty">Sin turnos</span>'}
                        </div>
                    </button>
                `);
            }

            const trailingCells = (7 - (dayCells.length % 7)) % 7;
            for (let day = 1; day <= trailingCells; day += 1) {
                dayCells.push(`
                    <div class="calendar-month-cell is-outside-month" aria-hidden="true">
                        <div class="calendar-month-cell-top">
                            <span class="calendar-month-day-number">${day}</span>
                        </div>
                        <div class="calendar-month-preview">
                            <span class="calendar-month-preview-empty">Sin turnos</span>
                        </div>
                    </div>
                `);
            }

            const hasAnyEvent = state.events.length > 0;
            const monthHasEvents = Object.keys(eventsByDate).some(key => {
                const date = new Date(`${key}T12:00:00`);
                return isSameMonth(date, monthStart);
            });

            calendarEl.innerHTML = `
                <div class="calendar-month-shell">
                    <div class="calendar-month-toolbar">
                        <div>
                            <div class="calendar-month-toolbar-label">Mes actual</div>
                            <h3>${club360EscapeHtml(club360FormatMonthYear(monthStart))}</h3>
                        </div>
                        <div class="calendar-month-toolbar-actions">
                            <button type="button" class="calendar-nav-btn" data-calendar-nav="today">Hoy</button>
                            <button type="button" class="calendar-nav-btn" data-calendar-nav="prev" aria-label="Mes anterior">‹</button>
                            <button type="button" class="calendar-nav-btn" data-calendar-nav="next" aria-label="Mes siguiente">›</button>
                        </div>
                    </div>
                    ${!hasAnyEvent ? `
                        <div class="calendar-inline-empty">
                            <div class="calendar-surface-empty-badge">Sin actividad</div>
                            <strong>${club360EscapeHtml(config.emptyCalendarTitle || 'No hay turnos cargados')}</strong>
                            <span>${club360EscapeHtml(config.emptyCalendarMessage || 'Todavía no hay eventos para mostrar en este calendario.')}</span>
                        </div>
                    ` : !monthHasEvents ? `
                        <div class="calendar-inline-empty">
                            <div class="calendar-surface-empty-badge">Mes sin actividad</div>
                            <strong>No hay turnos en ${club360EscapeHtml(club360FormatMonthYear(monthStart))}</strong>
                            <span>Podés navegar a otro mes para revisar la agenda o crear nuevos turnos.</span>
                        </div>
                    ` : ''}
                    <div class="calendar-month-weekdays">
                        ${weekdayLabels.map(label => `<span>${label}</span>`).join('')}
                    </div>
                    <div class="calendar-month-grid">
                        ${dayCells.join('')}
                    </div>
                </div>
            `;

            calendarEl.querySelectorAll('[data-calendar-nav]').forEach(button => {
                button.addEventListener('click', function() {
                    if (button.dataset.calendarNav === 'today') {
                        const today = new Date();
                        state.currentMonth = startOfMonth(today);
                        renderCalendar();
                        setSelectedDate(club360ToDateKey(today));
                        return;
                    } else if (button.dataset.calendarNav === 'prev') {
                        state.currentMonth = new Date(monthStart.getFullYear(), monthStart.getMonth() - 1, 1);
                    } else if (button.dataset.calendarNav === 'next') {
                        state.currentMonth = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 1);
                    }
                    renderCalendar();
                });
            });

            calendarEl.querySelectorAll('[data-calendar-date]').forEach(button => {
                button.addEventListener('click', function() {
                    setSelectedDate(button.dataset.calendarDate);
                });
            });

            updateSelectedDayStyle();
        }

        fetch(config.eventsUrl, {
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const contentType = response.headers.get('content-type') || '';
                if (!contentType.includes('application/json')) {
                    throw new Error('Respuesta no JSON');
                }
                return response.json();
            })
            .then(events => {
                state.events = Array.isArray(events)
                    ? events.map(event => ({ ...event, id: String(event.id) }))
                    : [];
                renderCalendar();
                renderAgenda();
            })
            .catch(error => {
                console.error('Club360 calendar load error:', error);
                renderCalendarError(
                    'No se pudo cargar la agenda',
                    'Hubo un problema al obtener los turnos. Recargá la página o revisá la sesión.'
                );
            });
    }
};

window.Club360Dialogs = {
    showNotice() {}
};

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

        if (trigger.tagName === 'A' || trigger.tagName === 'BUTTON') {
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
