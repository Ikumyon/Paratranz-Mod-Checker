document.addEventListener('DOMContentLoaded', () => {
    // Scroll Reveal Animation
    const revealElements = document.querySelectorAll('.feature-card, .focus-text, .focus-visual, .download-box');
    
    const revealOnScroll = () => {
        const triggerBottom = window.innerHeight / 5 * 4;
        
        revealElements.forEach(el => {
            const elTop = el.getBoundingClientRect().top;
            
            if (elTop < triggerBottom) {
                el.style.opacity = '1';
                el.style.transform = 'translateY(0)';
            }
        });
    };

    // Initial styles for reveal elements
    revealElements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(30px)';
        el.style.transition = 'all 0.8s ease-out';
    });

    window.addEventListener('scroll', revealOnScroll);
    revealOnScroll(); // Initial check

    // Navbar background change on scroll
    const navbar = document.getElementById('navbar');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            navbar.style.background = 'rgba(10, 10, 20, 0.95)';
            navbar.style.padding = '5px 0';
        } else {
            navbar.style.background = 'rgba(15, 15, 26, 0.8)';
            navbar.style.padding = '0';
        }
    });

    // Smooth scroll for nav links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                window.scrollTo({
                    top: target.offsetTop - 70,
                    behavior: 'smooth'
                });
            }
        });
    });

    // Google Analytics Event Tracking for Downloads
    const downloadButtons = [
        { id: 'btn-hero-download', label: 'Hero Section' },
        { id: 'btn-final-download', label: 'Bottom Box' },
        { selector: '.nav-container .btn-small', label: 'Navbar' }
    ];

    downloadButtons.forEach(btn => {
        const element = btn.id ? document.getElementById(btn.id) : document.querySelector(btn.selector);
        if (element) {
            element.addEventListener('click', () => {
                if (typeof gtag === 'function') {
                    gtag('event', 'app_download', {
                        'event_category': 'engagement',
                        'event_label': btn.label,
                        'file_name': 'Paratranz_Mod_Checker.zip'
                    });
                    console.log('GA Event Sent: app_download from ' + btn.label);
                }
            });
        }
    });
});
