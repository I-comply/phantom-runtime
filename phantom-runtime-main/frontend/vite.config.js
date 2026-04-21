import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path, { dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [
    react({
      babel: {
        parserOpts: {
          plugins: ['jsx']
        }
      }
    })
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  builder: {
    type: 'esbuild'
  },
  esbuild: {
    loader: 'jsx',
    include: /src\/.*\.[jt]sx?$/,
  },
  optimizeDeps: {
    esbuildOptions: {
      loader: {
        '.js': 'jsx',
        '.jsx': 'jsx',
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 3000
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    hmr: {
      clientPort: 443
    },
    allowedHosts: [
      'phantom-runtime.cluster-0.preview.emergentcf.cloud',
      'phantom-runtime.preview.emergentagent.com',
      '.preview.emergentagent.com',
      '.emergentcf.cloud'
    ]
  }
})
