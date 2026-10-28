// Minimal service worker: makes the web app installable on the desktop. It caches nothing:
// letters and jobs always come from the server. (The phone uses the Android app.)
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
