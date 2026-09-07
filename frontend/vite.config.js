import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // Проект лежит на Windows-диске, смонтированном в контейнер — нативные
    // файловые события (inotify) через такой bind-mount не доходят, поэтому
    // без polling правки просто не подхватываются до ручного перезапуска
    watch: {
      usePolling: true,
      interval: 300,
    },
    // В разработке фронт и бэк на разных портах — проксируем, чтобы не
    // возиться с CORS и держать один и тот же путь /api/v1, что и в проде
    proxy: {
      '/api': {
        target: 'http://api:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          antd: ['antd', '@ant-design/icons'],
          charts: ['recharts'],
        },
      },
    },
  },
})
