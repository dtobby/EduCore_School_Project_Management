<template>
  <div class="login-page">
    <div class="login-card">
      <h1>EduCore</h1>
      <p class="subtitle">School Project Management</p>

      <form @submit.prevent="submit">
        <div class="field">
          <label for="username">Username</label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            placeholder="e.g. teacher1"
            required
          />
        </div>

        <div class="field">
          <label for="password">Password</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="••••••••"
            required
          />
        </div>

        <p v-if="error" class="error">{{ error }}</p>

        <button type="submit" :disabled="loading">
          {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>

      <p class="hint">Demo: teacher1 / teacher123 &nbsp;·&nbsp; student1 / student123</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    router.push('/projects')
  } catch (err) {
    error.value = err.response?.status === 401
      ? 'Incorrect username or password.'
      : 'Could not reach the server. Is Docker running?'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 1rem;
}

.login-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0,0,0,.08);
  padding: 2.5rem 2rem;
  width: 100%;
  max-width: 380px;
  text-align: center;
}

h1 { font-size: 1.8rem; color: #2563eb; margin-bottom: .25rem; }
.subtitle { color: #6b7280; font-size: .9rem; margin-bottom: 2rem; }

.field { text-align: left; margin-bottom: 1rem; }
label { display: block; font-size: .85rem; font-weight: 600; color: #374151; margin-bottom: .35rem; }
input {
  width: 100%; padding: .6rem .8rem;
  border: 1.5px solid #d1d5db; border-radius: 8px;
  font-size: .95rem; outline: none; transition: border-color .15s;
}
input:focus { border-color: #2563eb; }

.error {
  background: #fee2e2; color: #991b1b;
  border-radius: 6px; padding: .6rem .8rem;
  font-size: .85rem; margin-bottom: .75rem; text-align: left;
}

button {
  width: 100%; padding: .7rem;
  background: #2563eb; color: #fff;
  border: none; border-radius: 8px;
  font-size: 1rem; font-weight: 600; cursor: pointer;
  transition: background .15s;
}
button:hover:not(:disabled) { background: #1d4ed8; }
button:disabled { opacity: .6; cursor: not-allowed; }

.hint { margin-top: 1.5rem; font-size: .78rem; color: #9ca3af; }
</style>
