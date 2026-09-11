import type { NextConfig } from "next";

/**
 * Configurazione Next.js
 *
 * Environment variables supportate:
 * - BACKEND_URL: URL del backend per il proxy API (default: http://localhost:8000)
 * - NEXT_PUBLIC_API_URL: URL pubblico dell'API per il frontend (opzionale)
 */
const backendUrl = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Output standalone per Docker production
  output: 'standalone',

  // Ottimizza la gestione delle immagini in produzione
  images: {
    unoptimized: process.env.NODE_ENV === 'production',
  },

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
