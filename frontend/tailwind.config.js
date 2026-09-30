/**
 * HoneyChain design tokens.
 *
 * The palette is deliberately agriculture-inspired rather than "crypto":
 * honey gold for accents, deep forest green for structure and actions, warm
 * neutrals for surfaces. Every later module should compose these tokens instead
 * of introducing new hard-coded colours.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Primary accent — honey / golden with a slight amber bias.
        honey: {
          50: '#FEF9EC',
          100: '#FCEDCD',
          200: '#F8DC9C',
          300: '#F2C765',
          400: '#E9AE37',
          500: '#D99A2B', // primary accent
          600: '#B87A1E',
          700: '#915C19',
          800: '#6B4415',
          900: '#472D0F',
        },
        // Secondary — deep green (leaf / forests, KVIC & agriculture identity).
        forest: {
          50: '#F1F7F2',
          100: '#DDEBE0',
          200: '#BBD7C2',
          300: '#8FBB9B',
          400: '#5E9670',
          500: '#3D7A52',
          600: '#2C6141',
          700: '#234D35',
          800: '#1B3D2A',
          900: '#123020', // deep green for headers/footers
        },
        // Warm neutrals — backgrounds and borders (never cold grey).
        sand: {
          50: '#FDFBF7', // page background
          100: '#F7F3EA',
          200: '#EFE9DC',
          300: '#E1D9C8',
          400: '#C9BFA9',
          500: '#A79B84',
          600: '#7D7361',
          700: '#57503F',
          800: '#3A3529',
          900: '#232019',
        },
        ink: {
          DEFAULT: '#1C2B24', // primary text
          soft: '#4A5A51',    // secondary text
          muted: '#6F7D75',   // tertiary text
        },
        // Status colours keep their conventional meaning across the platform.
        status: {
          success: '#2C7A4B',
          'success-bg': '#E8F5EC',
          warning: '#B77B14',
          'warning-bg': '#FDF3E0',
          danger: '#B3261E',
          'danger-bg': '#FBEAE9',
          info: '#1F5F8B',
          'info-bg': '#E7F1F8',
          pending: '#6B5BD2',
          'pending-bg': '#EFEDFB',
        },
      },
      fontFamily: {
        sans: ['"Inter"', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['"Source Serif 4"', 'Georgia', 'Cambria', 'serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        card: '0.75rem',
      },
      boxShadow: {
        // Minimal, soft elevation — the platform should read as institutional.
        card: '0 1px 2px rgba(28, 43, 36, 0.04), 0 1px 3px rgba(28, 43, 36, 0.06)',
        raised: '0 4px 12px rgba(28, 43, 36, 0.08)',
        focus: '0 0 0 3px rgba(217, 154, 43, 0.35)',
      },
      maxWidth: {
        content: '80rem',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 200ms ease-out',
        'slide-up': 'slide-up 260ms ease-out',
      },
    },
  },
  plugins: [],
};
