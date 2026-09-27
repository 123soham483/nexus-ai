import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        base: 'var(--bg-base)',
        surface: 'var(--bg-surface)',
        elevated: 'var(--bg-elevated)',
        border: 'var(--bg-border)',
        brand: {
          DEFAULT: 'var(--brand-primary)',
          light: 'var(--brand-secondary)',
          glow: 'var(--brand-glow)',
        },
        success: 'var(--status-success)',
        warning: 'var(--status-warning)',
        error: 'var(--status-error)',
        info: 'var(--status-info)',
        text: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
          accent: 'var(--text-accent)',
        },
        agent: {
          coder: 'var(--agent-coder)',
          tester: 'var(--agent-tester)',
          security: 'var(--agent-security)',
          docs: 'var(--agent-docs)',
          planner: 'var(--agent-planner)',
          reviewer: 'var(--agent-reviewer)',
          optimizer: 'var(--agent-optimizer)',
          debugger: 'var(--agent-debugger)',
          validator: 'var(--agent-validator)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
        display: ['Playfair Display', 'Georgia', 'serif'],
      },
      borderRadius: {
        card: '12px',
        button: '8px',
        input: '8px',
      },
      boxShadow: {
        glow: '0 0 24px var(--brand-glow)',
        card: '0 1px 2px rgb(0 0 0 / 0.4), 0 4px 16px rgb(0 0 0 / 0.25)',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in-right': {
          from: { opacity: '0', transform: 'translateX(12px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        'pulse-dot': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        'border-pulse': {
          '0%, 100%': { boxShadow: 'inset 3px 0 0 0 var(--brand-primary)' },
          '50%': { boxShadow: 'inset 3px 0 0 0 transparent' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-400px 0' },
          '100%': { backgroundPosition: '400px 0' },
        },
        'gold-pulse': {
          '0%, 100%': {
            boxShadow: '0 0 18px color-mix(in srgb, var(--brand-glow) 70%, transparent)',
          },
          '50%': {
            boxShadow: '0 0 30px color-mix(in srgb, var(--brand-glow) 100%, transparent)',
          },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.25s ease-out',
        'slide-in-right': 'slide-in-right 0.25s ease-out',
        'pulse-dot': 'pulse-dot 1.2s ease-in-out infinite',
        float: 'float 5s ease-in-out infinite',
        'border-pulse': 'border-pulse 1.6s ease-in-out infinite',
        shimmer: 'shimmer 1.6s linear infinite',
        'gold-pulse': 'gold-pulse 2.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config
