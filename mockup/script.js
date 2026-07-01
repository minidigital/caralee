document.getElementById('dismiss-banner')?.addEventListener('click', () => {
  document.getElementById('preview-banner')?.classList.add('hidden');
  localStorage.setItem('caralee-banner-dismissed', '1');
});

if (localStorage.getItem('caralee-banner-dismissed')) {
  document.getElementById('preview-banner')?.classList.add('hidden');
}

const toggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('.main-nav');
const cta = document.querySelector('.header-cta');

toggle?.addEventListener('click', () => {
  const open = nav.classList.toggle('open');
  cta.classList.toggle('open', open);
  toggle.setAttribute('aria-expanded', open);
});

document.querySelectorAll('.main-nav a').forEach(link => {
  link.addEventListener('click', () => {
    nav.classList.remove('open');
    cta.classList.remove('open');
    toggle.setAttribute('aria-expanded', 'false');
  });
});

const sections = document.querySelectorAll('section[id]');
const navLinks = document.querySelectorAll('.main-nav a');

const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      navLinks.forEach(link => {
        link.classList.toggle('active', link.getAttribute('href') === `#${entry.target.id}`);
      });
    }
  });
}, { rootMargin: '-40% 0px -50% 0px' });

sections.forEach(section => observer.observe(section));

const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const today = days[new Date().getDay()];
document.querySelectorAll('.hours-list li').forEach(li => {
  if (li.querySelector('span')?.textContent === today) {
    li.classList.add('today');
  }
});
