import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import LoginView from '../views/LoginView.vue'
import ProjectListView from '../views/ProjectListView.vue'

const routes = [
  { path: '/', redirect: '/projects' },
  { path: '/login', component: LoginView },
  {
    path: '/projects',
    component: ProjectListView,
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Guard: redirect to /login if the route needs auth and the user has no token.
// Pinia store isn't ready until after createApp, so we import it lazily inside the guard.
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return '/login'
  }
})

export default router
