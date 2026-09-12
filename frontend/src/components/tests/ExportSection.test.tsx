/**
 * Test per ExportSection
 * 
 * Copre:
 * - Rendering stato iniziale
 * - Submit esportazione
 * - Gestione errore submit
 * - Visualizzazione job in corso (pending/running)
 * - Visualizzazione job fallito
 * - Visualizzazione video completato
 * - QA verdict (approved/issues)
 * - Stato busy durante rendering
 * - Download link
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExportSection } from '../ExportSection';
import type { ProjectState, Job } from '@/lib/api';

const mockProject: ProjectState = {
  project_id: 'test-project',
  name: 'Test Project',
  media: [{ id: 'm1', source: 'local', path: '/test.mp4', type: 'video', orientation: 'landscape', width: 1920, height: 1080, duration_sec: 30, order_index: 0, fit_mode: 'cover', background_fill: 'blur' }],
  output_spec: { resolution: '1920x1080', fps: 30, vcodec: 'h264', background_fill: 'blur' },
  clip_overrides: {},
  edit_decision_list: [],
};

const mockJobPending: Job = {
  id: 'job-1',
  kind: 'render',
  status: 'pending',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  progress: { fraction: 0, label: 'In coda' },
};

const mockJobRunning: Job = {
  id: 'job-1',
  kind: 'render',
  status: 'running',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  progress: { fraction: 0.5, label: 'Rendering', note: 'Clip 3/10' },
};

const mockJobFailed: Job = {
  ...mockJobRunning,
  status: 'failed',
  error: 'FFmpeg error: codec not found',
};

const mockProjectDone: ProjectState = {
  ...mockProject,
  render_manifest: {
    status: 'done',
    total_sec: 45.5,
    output: { resolution: '1920x1080', fps: 30, size_bytes: 12345678 },
  },
};

describe('ExportSection', () => {
  const mockOnSubmit = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renderizza stato iniziale con pulsante Esporta', () => {
    render(<ExportSection project={mockProject} onSubmit={mockOnSubmit} />);
    
    expect(screen.getByText('Video finale')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /🎬 Esporta video/i })).toBeInTheDocument();
    expect(screen.getByText(/L'esportazione monta il video/i)).toBeInTheDocument();
  });

  it('disabilita pulsante quando non ci sono media', () => {
    const projectWithoutMedia = { ...mockProject, media: [] };
    render(<ExportSection project={projectWithoutMedia} onSubmit={mockOnSubmit} />);
    
    expect(screen.getByRole('button', { name: /🎬 Esporta video/i })).toBeDisabled();
  });

  it('chiama onSubmit quando si clicca Esporta', async () => {
    const user = userEvent.setup();
    render(<ExportSection project={mockProject} onSubmit={mockOnSubmit} />);
    
    await user.click(screen.getByRole('button', { name: /🎬 Esporta video/i }));
    
    expect(mockOnSubmit).toHaveBeenCalledTimes(1);
  });

  it('mostra stato di submitting dopo click', async () => {
    mockOnSubmit.mockImplementationOnce(() => new Promise(resolve => setTimeout(resolve, 100)));
    const user = userEvent.setup();
    render(<ExportSection project={mockProject} onSubmit={mockOnSubmit} />);
    
    await user.click(screen.getByRole('button', { name: /🎬 Esporta video/i }));
    
    expect(screen.getByText('Rendering…')).toBeInTheDocument();
  });

  it('mostra errore se onSubmit fallisce', async () => {
    mockOnSubmit.mockRejectedValueOnce(new Error('Errore di esportazione'));
    const user = userEvent.setup();
    render(<ExportSection project={mockProject} onSubmit={mockOnSubmit} />);
    
    await user.click(screen.getByRole('button', { name: /🎬 Esporta video/i }));
    
    await waitFor(() => {
      expect(screen.getByText('Errore di esportazione')).toBeInTheDocument();
    });
  });

  it('mostra barra di avanzamento quando job è pending', () => {
    render(<ExportSection project={mockProject} onSubmit={mockOnSubmit} job={mockJobPending} />);
    
    expect(screen.getByText('In coda…')).toBeInTheDocument();
    // La barra di avanzamento è un div con role implicito, verifichiamo la presenza del testo e della struttura
    expect(screen.getByLabelText(/Avanzamento rendering/i)).toBeInTheDocument();
  });

  it('mostra barra di avanzamento quando job è running', () => {
    render(<ExportSection project={mockProject} onSubmit={mockOnSubmit} job={mockJobRunning} />);
    
    expect(screen.getByText(/Rendering.*50%/i)).toBeInTheDocument();
    expect(screen.getByText(/Clip 3\/10/i)).toBeInTheDocument();
  });

  it('disabilita pulsante durante job attivo', () => {
    render(<ExportSection project={mockProject} onSubmit={mockOnSubmit} job={mockJobRunning} />);
    
    expect(screen.getByRole('button', { name: /Rendering…/i })).toBeDisabled();
  });

  it('mostra errore job fallito', () => {
    render(<ExportSection project={mockProject} onSubmit={mockOnSubmit} job={mockJobFailed} />);
    
    expect(screen.getByText(/Rendering fallito:/i)).toBeInTheDocument();
    expect(screen.getByText(/codec not found/i)).toBeInTheDocument();
  });

  it('mostra video e download quando completato', () => {
    render(<ExportSection project={mockProjectDone} onSubmit={mockOnSubmit} />);
    
    expect(screen.getByRole('button', { name: /↻ Riesporta/i })).toBeInTheDocument();
    expect(screen.getByText('45.5s')).toBeInTheDocument();
    expect(screen.getByText(/1920x1080.*30fps/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /⬇ Scarica mp4/i })).toHaveAttribute('href', '/api/projects/test-project/download');
  });

  it('mostra QA verdict approvato', () => {
    const projectWithQaApproved: ProjectState = {
      ...mockProjectDone,
      qa_report: { status: 'approved', checks: [{ name: 'duration', detail: 'OK' }] },
    };
    render(<ExportSection project={projectWithQaApproved} onSubmit={mockOnSubmit} />);
    
    expect(screen.getByText(/QA superato/i)).toBeInTheDocument();
  });

  it('mostra QA verdict con problemi', () => {
    const projectWithQaIssues: ProjectState = {
      ...mockProjectDone,
      qa_report: {
        status: 'issues',
        issues: [
          { check: 'duration', message: 'Video troppo corto', route_to: 'montage' },
          { check: 'verticals', message: 'Verticali presenti', route_to: 'settings' },
        ],
        checks: [],
      },
    };
    render(<ExportSection project={projectWithQaIssues} onSubmit={mockOnSubmit} />);
    
    expect(screen.getByText(/QA: 2 problemi da correggere/i)).toBeInTheDocument();
    expect(screen.getByText('Video troppo corto')).toBeInTheDocument();
    expect(screen.getByText('Verticali presenti')).toBeInTheDocument();
    expect(screen.getByText(/montage/i)).toBeInTheDocument();
    expect(screen.getByText(/settings/i)).toBeInTheDocument();
  });

  it('permette riesportazione dopo completamento', async () => {
    const user = userEvent.setup();
    render(<ExportSection project={mockProjectDone} onSubmit={mockOnSubmit} />);
    
    await user.click(screen.getByRole('button', { name: /↻ Riesporta/i }));
    
    expect(mockOnSubmit).toHaveBeenCalledTimes(1);
  });

  it('cambia testo pulsante a "Riesporta" dopo completamento', () => {
    render(<ExportSection project={mockProjectDone} onSubmit={mockOnSubmit} />);
    
    expect(screen.getByRole('button', { name: /↻ Riesporta/i })).toBeInTheDocument();
  });

  it('mostra dimensione file se disponibile', () => {
    render(<ExportSection project={mockProjectDone} onSubmit={mockOnSubmit} />);
    
    // 12345678 bytes ≈ 11.8 MB
    expect(screen.getByText(/11\.8 MB/i)).toBeInTheDocument();
  });
});
