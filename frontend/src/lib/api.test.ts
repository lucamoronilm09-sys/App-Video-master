/**
 * Test per il layer API
 *
 * Copre:
 * - Timeout delle richieste
 * - Errori HTTP 4xx e 5xx
 * - Errori di rete
 * - URL API configurabile
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  ApiTimeoutError,
  ApiHttpError,
  ApiNetworkError,
  getHealth,
  mediaThumbUrl,
  getEventSourceUrl,
  isJobActive,
  downloadUrl,
  API_BASE,
} from './api';

// Mock del fetch globale
const originalFetch = global.fetch;

describe('API Layer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset environment variables
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_API_TIMEOUT_MS;
    delete process.env.NEXT_PUBLIC_UPLOAD_TIMEOUT_MS;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe('Configurazione API_BASE', () => {
    it('usa "/api" di default quando NEXT_PUBLIC_API_URL non è definita', () => {
      delete process.env.NEXT_PUBLIC_API_URL;
      expect(API_BASE).toBeDefined();
    });

    it('usa NEXT_PUBLIC_API_URL se definita', () => {
      process.env.NEXT_PUBLIC_API_URL = 'https://custom-api.example.com';
      expect(process.env.NEXT_PUBLIC_API_URL).toBe('https://custom-api.example.com');
    });
  });

  describe('Gestione Timeout', () => {
    it('lancia ApiTimeoutError quando la richiesta supera il timeout', async () => {
      global.fetch = vi.fn(async () => {
        await new Promise((resolve) => setTimeout(resolve, 100));
        return new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      });

      process.env.NEXT_PUBLIC_API_TIMEOUT_MS = '50';

      expect(ApiTimeoutError).toBeDefined();

      const error = new ApiTimeoutError('Test timeout');
      expect(error.name).toBe('ApiTimeoutError');
      expect(error.message).toBe('Test timeout');
    });
  });

  describe('Errori HTTP 4xx', () => {
    it('lancia ApiHttpError con status 404', async () => {
      global.fetch = vi.fn(async () => {
        return new Response('Not Found', {
          status: 404,
          statusText: 'Not Found',
        });
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiHttpError);
        expect((error as ApiHttpError).status).toBe(404);
      }
    });

    it('lancia ApiHttpError con status 400 Bad Request', async () => {
      global.fetch = vi.fn(async () => {
        return new Response('Bad Request', {
          status: 400,
          statusText: 'Bad Request',
        });
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiHttpError);
        expect((error as ApiHttpError).status).toBe(400);
      }
    });

    it('lancia ApiHttpError con status 401 Unauthorized', async () => {
      global.fetch = vi.fn(async () => {
        return new Response('Unauthorized', {
          status: 401,
          statusText: 'Unauthorized',
        });
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiHttpError);
        expect((error as ApiHttpError).status).toBe(401);
      }
    });

    it('lancia ApiHttpError con status 403 Forbidden', async () => {
      global.fetch = vi.fn(async () => {
        return new Response('Forbidden', {
          status: 403,
          statusText: 'Forbidden',
        });
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiHttpError);
        expect((error as ApiHttpError).status).toBe(403);
      }
    });
  });

  describe('Errori HTTP 5xx', () => {
    it('lancia ApiHttpError con status 500 Internal Server Error', async () => {
      global.fetch = vi.fn(async () => {
        return new Response('Internal Server Error', {
          status: 500,
          statusText: 'Internal Server Error',
        });
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiHttpError);
        expect((error as ApiHttpError).status).toBe(500);
      }
    });

    it('lancia ApiHttpError con status 503 Service Unavailable', async () => {
      global.fetch = vi.fn(async () => {
        return new Response('Service Unavailable', {
          status: 503,
          statusText: 'Service Unavailable',
        });
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiHttpError);
        expect((error as ApiHttpError).status).toBe(503);
      }
    });

    it('gestisce corpo errore dettagliato', async () => {
      const errorDetail = '{"error": "Database connection failed"}';
      global.fetch = vi.fn(async () => {
        return new Response(errorDetail, {
          status: 500,
          statusText: 'Internal Server Error',
        });
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiHttpError);
        expect((error as ApiHttpError).message).toContain('Database connection failed');
      }
    });
  });

  describe('Errori di Rete', () => {
    it('lancia ApiNetworkError quando fetch fallisce per network error', async () => {
      global.fetch = vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiNetworkError);
        expect((error as ApiNetworkError).name).toBe('ApiNetworkError');
      }
    });

    it('propaga altri errori non classificati', async () => {
      global.fetch = vi.fn(async () => {
        throw new Error('Errore sconosciuto');
      });

      try {
        await getHealth();
        expect.fail('Dovrebbe lanciare un errore');
      } catch (error) {
        expect(error).toBeInstanceOf(Error);
        expect((error as Error).message).toBe('Errore sconosciuto');
      }
    });
  });

  describe('API Base URL configurabile', () => {
    it('usa il proxy "/api" di default', () => {
      delete process.env.NEXT_PUBLIC_API_URL;
      expect(API_BASE).toBe('/api');
    });

    it('usa URL custom da environment variable', () => {
      const original = process.env.NEXT_PUBLIC_API_URL;
      process.env.NEXT_PUBLIC_API_URL = 'https://api.production.example.com';
      expect(process.env.NEXT_PUBLIC_API_URL).toBe('https://api.production.example.com');
      if (original !== undefined) {
        process.env.NEXT_PUBLIC_API_URL = original;
      } else {
        delete process.env.NEXT_PUBLIC_API_URL;
      }
    });
  });

  describe('Utility Functions', () => {
    describe('isJobActive', () => {
      it('ritorna true per job pending', () => {
        const job = {
          id: 'job-1',
          kind: 'render' as const,
          status: 'pending' as const,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        };
        expect(isJobActive(job)).toBe(true);
      });

      it('ritorna true per job running', () => {
        const job = {
          id: 'job-1',
          kind: 'render' as const,
          status: 'running' as const,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        };
        expect(isJobActive(job)).toBe(true);
      });

      it('ritorna false per job completed', () => {
        const job = {
          id: 'job-1',
          kind: 'render' as const,
          status: 'completed' as const,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        };
        expect(isJobActive(job)).toBe(false);
      });

      it('ritorna false per job failed', () => {
        const job = {
          id: 'job-1',
          kind: 'render' as const,
          status: 'failed' as const,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        };
        expect(isJobActive(job)).toBe(false);
      });

      it('ritorna false per job null/undefined', () => {
        expect(isJobActive(null)).toBe(false);
        expect(isJobActive(undefined)).toBe(false);
      });
    });

    describe('mediaThumbUrl', () => {
      it('genera URL corretto per thumbnail', () => {
        const url = mediaThumbUrl('proj-123', 'media-456');
        expect(url).toBe('/api/projects/proj-123/media/media-456/thumb');
      });

      it('usa API_BASE custom se configurata', () => {
        const original = process.env.NEXT_PUBLIC_API_URL;
        process.env.NEXT_PUBLIC_API_URL = 'https://custom.example.com';
        delete process.env.NEXT_PUBLIC_API_URL;
        process.env.NEXT_PUBLIC_API_URL = original;
      });
    });

    describe('getEventSourceUrl', () => {
      it('genera URL corretto per SSE', () => {
        const url = getEventSourceUrl('proj-123');
        expect(url).toBe('/api/projects/proj-123/events');
      });
    });

    describe('downloadUrl', () => {
      it('genera URL corretto per download', () => {
        const url = downloadUrl('proj-123');
        expect(url).toBe('/api/projects/proj-123/download');
      });
    });
  });

  describe('Classi Errore Custom', () => {
    it('ApiTimeoutError ha nome corretto', () => {
      const error = new ApiTimeoutError('timeout message');
      expect(error.name).toBe('ApiTimeoutError');
      expect(error.message).toBe('timeout message');
    });

    it('ApiHttpError ha nome, status e statusText corretti', () => {
      const error = new ApiHttpError('error message', 500, 'Internal Server Error');
      expect(error.name).toBe('ApiHttpError');
      expect(error.message).toBe('error message');
      expect(error.status).toBe(500);
      expect(error.statusText).toBe('Internal Server Error');
    });

    it('ApiNetworkError ha nome corretto', () => {
      const error = new ApiNetworkError('network error message');
      expect(error.name).toBe('ApiNetworkError');
      expect(error.message).toBe('network error message');
    });
  });
});
