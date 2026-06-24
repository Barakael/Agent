import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  preview: {
    host: true,
    allowedHosts: ['wayda.teratech.co.tz', 'wayda.teratech', '147.79.101.245', 'localhost'],
  },
})
