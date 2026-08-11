/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        forest: { 900: '#0d1b0f', 800: '#1a2f1a', 700: '#1a472a', 600: '#2d5a3d' },
        gold: { 400: '#f4d03f', 500: '#d4a827' },
        cream: '#e8e4d9',
      },
      fontFamily: {
        sans: ['Noto Sans SC', 'sans-serif'],
      },
    },
  },
  plugins: [],
}