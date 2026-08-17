// macOS-style auto-hide navigation bar
(function() {
    // Create navbar HTML
    const navbarHTML = `
        <nav class="macos-navbar" id="macosNavbar">
            <a href="/slide.html">Slideshow</a>
            <a href="/metadata.html">Gallery</a>
            <a href="/videos.html">Videos</a>
            <a href="/cropper.html">Cropper</a>
            <span class="separator"></span>
            <a href="http://192.168.0.222:8188/" target="_blank">Comfyui</a>
        </nav>
    `;
    
    // Insert navbar at the beginning of body
    document.addEventListener('DOMContentLoaded', function() {
        document.body.insertAdjacentHTML('afterbegin', navbarHTML);
        
        const navbar = document.getElementById('macosNavbar');
        let hideTimeout;
        let isVisible = false;
        
        // Mark active page
        const currentPath = window.location.pathname;
        const links = navbar.querySelectorAll('a');
        links.forEach(link => {
            const linkPath = new URL(link.href).pathname;
            if (currentPath === linkPath || (currentPath === '/' && linkPath === '/slide.html')) {
                link.classList.add('active');
            }
        });
        
        // Show navbar on mouse move to top
        function showNavbar() {
            navbar.classList.add('visible');
            isVisible = true;
            resetHideTimer();
        }
        
        function hideNavbar() {
            navbar.classList.remove('visible');
            isVisible = false;
        }
        
        function resetHideTimer() {
            clearTimeout(hideTimeout);
            hideTimeout = setTimeout(() => {
                hideNavbar();
            }, 2000); // Hide after 2 seconds
        }
        
        // Show navbar when mouse is near top of screen
        document.addEventListener('mousemove', function(e) {
            if (e.clientY < 50) {
                showNavbar();
            }
        });
        
        // Keep navbar visible when hovering over it
        navbar.addEventListener('mouseenter', function() {
            clearTimeout(hideTimeout);
        });
        
        navbar.addEventListener('mouseleave', function() {
            resetHideTimer();
        });
        
        // Show navbar briefly on page load
        showNavbar();
    });
})();
