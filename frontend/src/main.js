import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)

// Pinia must be installed before the router guard runs (guard calls useAuthStore).
app.use(createPinia())
app.use(router)

app.mount('#app')
