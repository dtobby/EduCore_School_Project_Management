<template>
  <div class="page">
    <!-- Header -->
    <header class="topbar">
      <span class="brand">EduCore</span>
      <div class="user-info" v-if="auth.user">
        <span class="role-badge" :class="auth.user.role.toLowerCase()">{{ auth.user.role }}</span>
        <span class="username">{{ auth.user.username }}</span>
      </div>
      <button class="logout-btn" @click="logout">Sign out</button>
    </header>

    <!-- Content -->
    <main class="content">
      <h2>Projects</h2>

      <p v-if="loading" class="state-msg">Loading…</p>
      <p v-else-if="error" class="state-msg error">{{ error }}</p>
      <p v-else-if="projects.length === 0" class="state-msg">No projects found.</p>

      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Deadline</th>
              <th>Created by</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in projects" :key="p.id">
              <td class="title-cell">{{ p.title }}</td>
              <td><span class="badge" :class="p.status.toLowerCase()">{{ p.status }}</span></td>
              <td>{{ formatDate(p.deadline) }}</td>
              <td>{{ p.created_by?.username ?? '—' }}</td>
            </tr>
          </tbody>
        </table>

        <p class="count">{{ projects.length }} project{{ projects.length !== 1 ? 's' : '' }}</p>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const router = useRouter()
const auth = useAuthStore()

const projects = ref([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    // Fetch current user info and project list in parallel
    const [, projectsResp] = await Promise.all([
      auth.fetchMe(),
      api.get('/projects/'),
    ])
    projects.value = projectsResp.data.results ?? projectsResp.data
  } catch (err) {
    if (err.response?.status === 401) {
      auth.logout()
      router.push('/login')
    } else {
      error.value = 'Failed to load projects. Try refreshing.'
    }
  } finally {
    loading.value = false
  }
})

function logout() {
  auth.logout()
  router.push('/login')
}

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NZ', {
    day: 'numeric', month: 'short', year: 'numeric'
  })
}
</script>

<style scoped>
.page { display: flex; flex-direction: column; min-height: 100vh; }

/* ── top bar ── */
.topbar {
  display: flex; align-items: center; gap: 1rem;
  background: #fff; border-bottom: 1px solid #e5e7eb;
  padding: .75rem 1.5rem;
}
.brand { font-size: 1.1rem; font-weight: 700; color: #2563eb; margin-right: auto; }
.username { font-size: .9rem; color: #374151; }
.logout-btn {
  padding: .4rem .9rem; border-radius: 6px;
  background: transparent; border: 1.5px solid #d1d5db;
  font-size: .85rem; cursor: pointer; color: #374151; transition: background .15s;
}
.logout-btn:hover { background: #f3f4f6; }

/* ── content ── */
.content { padding: 2rem 1.5rem; max-width: 960px; width: 100%; margin: 0 auto; }
h2 { font-size: 1.4rem; margin-bottom: 1.25rem; color: #111827; }

.state-msg { color: #6b7280; font-size: .95rem; }
.state-msg.error { color: #b91c1c; }

/* ── table ── */
.table-wrap { background: #fff; border-radius: 10px; box-shadow: 0 1px 8px rgba(0,0,0,.06); overflow: hidden; }
table { width: 100%; border-collapse: collapse; }
thead { background: #f9fafb; }
th { padding: .75rem 1rem; text-align: left; font-size: .8rem; text-transform: uppercase;
     letter-spacing: .05em; color: #6b7280; border-bottom: 1px solid #e5e7eb; }
td { padding: .85rem 1rem; font-size: .9rem; border-bottom: 1px solid #f3f4f6; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f9fafb; }
.title-cell { font-weight: 500; }
.count { padding: .6rem 1rem; font-size: .8rem; color: #9ca3af; text-align: right; }

/* ── role badge ── */
.role-badge {
  display: inline-block; padding: .15rem .5rem; border-radius: 999px;
  font-size: .72rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
}
.role-badge.admin    { background: #fef3c7; color: #92400e; }
.role-badge.teacher  { background: #dbeafe; color: #1e40af; }
.role-badge.student  { background: #d1fae5; color: #065f46; }

/* ── status badge ── */
.badge {
  display: inline-block; padding: .2rem .6rem; border-radius: 999px;
  font-size: .75rem; font-weight: 600; letter-spacing: .03em;
}
.badge.draft        { background: #f3f4f6; color: #374151; }
.badge.in_progress  { background: #dbeafe; color: #1d4ed8; }
.badge.submitted    { background: #fef3c7; color: #92400e; }
.badge.graded       { background: #d1fae5; color: #065f46; }
</style>
