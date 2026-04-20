// Main JavaScript file for Club 360

document.addEventListener('DOMContentLoaded', function() {
    console.log('Club 360 - Sistema de Gestión de Turnos Deportivos');
});

// Toggle navbar menu on mobile
function toggleNavMenu() {
    const menu = document.querySelector('.navbar-menu');
    if (menu) {
        menu.classList.toggle('active');
    }
}

// Close alerts after 5 seconds
window.addEventListener('load', function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.display = 'none';
        }, 5000);
    });
});
