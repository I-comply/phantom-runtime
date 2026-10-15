import type { ReactNode } from 'react';

export const metadata = { title: 'iComply Control Panel' };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: 'system-ui, sans-serif', margin: 0, background: '#f9fafb', color: '#111827' }}>
        {children}
      </body>
    </html>
  );
}
