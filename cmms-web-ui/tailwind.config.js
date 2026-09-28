/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Logical properties for RTL/LTR support
      spacing: {
        'inline-start': 'var(--spacing-inline-start)',
        'inline-end': 'var(--spacing-inline-end)',
      },
      margin: {
        'inline-start': 'var(--margin-inline-start)',
        'inline-end': 'var(--margin-inline-end)',
      },
      padding: {
        'inline-start': 'var(--padding-inline-start)',
        'inline-end': 'var(--padding-inline-end)',
      },
      colors: {
        // Status colors (defined in CSS variables)
        'status-success': 'var(--color-status-success)',
        'status-warning': 'var(--color-status-warning)',
        'status-error': 'var(--color-status-error)',
        'status-info': 'var(--color-status-info)',
        // Safety colors
        'safety-low': 'var(--color-safety-low)',
        'safety-medium': 'var(--color-safety-medium)',
        'safety-high': 'var(--color-safety-high)',
        'safety-critical': 'var(--color-safety-critical)',
        // Priority colors
        'priority-low': 'var(--color-priority-low)',
        'priority-medium': 'var(--color-priority-medium)',
        'priority-high': 'var(--color-priority-high)',
        'priority-urgent': 'var(--color-priority-urgent)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
  // Important for logical properties
  corePlugins: {
    // Disable physical direction-specific plugins in favor of logical properties
    float: false,
    clear: false,
    margin: false,
    marginLeft: false,
    marginRight: false,
    padding: false,
    paddingLeft: false,
    paddingRight: false,
    space: false,
    divideWidth: false,
    borderLeft: false,
    borderRight: false,
    borderLeftWidth: false,
    borderRightWidth: false,
    borderRadius: false,
  },
};
