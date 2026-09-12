/**
 * Test per PipelineProgress
 * 
 * Copre:
 * - Rendering con log vuoto (null)
 * - Rendering stati stage (pending/running/done/failed)
 * - Colori e indicatori visivi
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PipelineProgress } from '../PipelineProgress';
import type { PipelineLogEntry } from '@/lib/api';

const mockLog: PipelineLogEntry[] = [
  { stage: 'intake', status: 'completed', timestamp: '2024-01-01T00:00:00Z' },
  { stage: 'normalizer', status: 'completed', timestamp: '2024-01-01T00:01:00Z' },
  { stage: 'sequence', status: 'running', timestamp: '2024-01-01T00:02:00Z' },
  { stage: 'audio_analysis', status: 'pending', timestamp: '2024-01-01T00:03:00Z' },
];

const mockLogFailed: PipelineLogEntry[] = [
  { stage: 'intake', status: 'completed', timestamp: '2024-01-01T00:00:00Z' },
  { stage: 'normalizer', status: 'failed', timestamp: '2024-01-01T00:01:00Z', error: 'File corrotto' },
];

describe('PipelineProgress', () => {
  it('non renderizza nulla con log vuoto', () => {
    const { container } = render(<PipelineProgress log={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renderizza tutti gli stage della pipeline', () => {
    render(<PipelineProgress log={mockLog} />);
    
    expect(screen.getByText('Drive')).toBeInTheDocument();
    expect(screen.getByText('Intake')).toBeInTheDocument();
    expect(screen.getByText('Normalizer')).toBeInTheDocument();
    expect(screen.getByText('Sequence')).toBeInTheDocument();
    expect(screen.getByText('Audio')).toBeInTheDocument();
    expect(screen.getByText('Regia')).toBeInTheDocument();
    expect(screen.getByText('Compiler')).toBeInTheDocument();
    expect(screen.getByText('Render')).toBeInTheDocument();
    expect(screen.getByText('QA')).toBeInTheDocument();
  });

  it('mostra stato completed per stage completati', () => {
    render(<PipelineProgress log={mockLog} />);
    
    // Verifica il titolo che indica lo stato done
    expect(screen.getByTitle(/Intake: done/i)).toBeInTheDocument();
  });

  it('mostra stato running per stage in esecuzione', () => {
    render(<PipelineProgress log={mockLog} />);
    
    // Verifica il titolo che indica lo stato running
    expect(screen.getByTitle(/Sequence: running/i)).toBeInTheDocument();
  });

  it('mostra stato pending per stage in attesa', () => {
    render(<PipelineProgress log={mockLog} />);
    
    // Verifica il titolo che indica lo stato pending
    expect(screen.getByTitle(/Audio: pending/i)).toBeInTheDocument();
  });

  it('mostra stato failed per stage falliti', () => {
    render(<PipelineProgress log={mockLogFailed} />);
    
    // Verifica il titolo che indica lo stato failed
    expect(screen.getByTitle(/Normalizer: failed/i)).toBeInTheDocument();
  });

  it('ha indicatori visivi per stati diversi', () => {
    render(<PipelineProgress log={mockLog} />);
    
    // Verifica che ci siano indicatori visivi (dot) per ogni stage
    const dots = screen.getAllByRole('listitem');
    expect(dots.length).toBeGreaterThan(0);
  });
});
