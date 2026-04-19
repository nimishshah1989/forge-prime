---
globs: ["frontend/**", "*.tsx", "*.ts", "*.jsx", "src/**/*.tsx", "src/**/*.ts"]
---
# Frontend conventions
- Indian number formatting: use `formatIndian()` for ₹ amounts. Never raw Intl.NumberFormat
- Indian units: lakh/crore always, never million/billion in user-visible text
- Dates: DD-MMM-YYYY format, IST timezone. Never ambiguous MM/DD/YYYY
- Component size: max 200 lines per component file. Split if larger
- No hardcoded API URLs — use `process.env.NEXT_PUBLIC_API_URL` or env config
- Error boundaries required on all async/streaming components
- TypeScript strict mode — `strict: true` in tsconfig.json
- No `console.log` in committed code (use a logging utility instead)
- Accessibility: all interactive elements must have accessible labels
- `npm run build` must succeed with zero TypeScript errors before shipping
