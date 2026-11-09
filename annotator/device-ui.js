'use strict';
// Decide once per page, including rotation. Desktop resizing keeps desktop controls.
(() => {
  const agent = navigator.userAgent;
  const ios = /iPhone|iPod/.test(agent);
  const android = /Android/.test(agent) && /Mobile/.test(agent);
  const profile = ios ? 'ios' : android ? 'android' : 'desktop';
  document.documentElement.dataset.ui = profile;
  document.documentElement.classList.toggle('mobile-ui', profile !== 'desktop');
  window.DeviceUI = Object.freeze({profile, mobile: profile !== 'desktop'});
})();

