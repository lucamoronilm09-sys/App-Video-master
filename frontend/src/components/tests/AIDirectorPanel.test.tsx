/**
 * Test per AIDirectorPanel
 * 
 * Copre:
 * - Rendering con stato iniziale
 * - Modifica prompt e stile
 * - Salvataggio automatico on blur
 * - Salvataggio manuale
 * - Gestione errori
 * - Stato busy/disabled
 * - Visualizzazione story chapters
 * - Visualizzazione music structure
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AIDirectorPanel } from '../AIDirectorPanel';
import type { ProjectState } from '@/lib/api';

const mockProject: ProjectState = {
  project_id: 'test-project',
  name: 'Test Project',
  media: [],
  user_prompt: 'Un viaggio emozionante tra amici',
  style_profile: 'cinematic',
  story_chapters: [
    { title: 'Inizio', start_index: 0, end_index: 2, media_ids: ['m1', 'm2'], reason: 'Introduzione' },
    { title: 'Climax', start_index: 2, end_index: 5, media_ids: ['m3', 'm4', 'm5'], reason: 'Momento chiave' },
  ],
  music_structure: {
    bpm: 120,
    energy: 0.7,
    climax_sec: 45.5,
    sections: [
      { label: 'Intro', start_sec: 0, end_sec: 15, energy: 0.3 },
      { label: 'Verse', start_sec: 15, end_sec: 45, energy: 0.6 },
      { label: 'Chorus', start_sec: 45, end_sec: 75, energy: 0.9 },
    ],
  },
  clip_overrides: {},
  edit_decision_list: [],
  output_spec: { resolution: '1920x1080', fps: 30, vcodec: 'h264', background_fill: 'blur' },
};

describe('AIDirectorPanel', () => {
  const mockOnSave = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renderizza correttamente con dati iniziali', () => {
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    expect(screen.getByText('AI Director')).toBeInTheDocument();
    expect(screen.getByText('Storia rilevata')).toBeInTheDocument();
    expect(screen.getByText('Struttura musicale')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Un viaggio emozionante tra amici')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveValue('cinematic');
  });

  it('mostra i capitoli della storia quando presenti', () => {
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    expect(screen.getByText('Inizio')).toBeInTheDocument();
    expect(screen.getByText('Climax')).toBeInTheDocument();
    expect(screen.getByText('2 media')).toBeInTheDocument();
    expect(screen.getByText('3 media')).toBeInTheDocument();
  });

  it('mostra la struttura musicale con BPM, energia e climax', () => {
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    expect(screen.getByText(/BPM 120/i)).toBeInTheDocument();
    expect(screen.getByText(/Energia 0\.7/i)).toBeInTheDocument();
    expect(screen.getByText(/Climax 45\.5s/i)).toBeInTheDocument();
    expect(screen.getByText('Intro')).toBeInTheDocument();
    expect(screen.getByText('Verse')).toBeInTheDocument();
    expect(screen.getByText('Chorus')).toBeInTheDocument();
  });

  it('mostra messaggio vuoto quando non ci sono capitoli', () => {
    const projectWithoutStory = { ...mockProject, story_chapters: [] };
    render(<AIDirectorPanel project={projectWithoutStory} onSave={mockOnSave} />);
    
    expect(screen.getByText(/Genera il montaggio/i)).toBeInTheDocument();
  });

  it('mostra messaggio vuoto quando non c\'è struttura musicale', () => {
    const projectWithoutMusic = { ...mockProject, music_structure: {} };
    render(<AIDirectorPanel project={projectWithoutMusic} onSave={mockOnSave} />);
    
    expect(screen.getByText(/Carica una traccia audio/i)).toBeInTheDocument();
  });

  it('aggiorna il prompt locale quando cambia il progetto', async () => {
    const { rerender } = render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    const newProject = { ...mockProject, user_prompt: 'Nuovo prompt aggiornato' };
    rerender(<AIDirectorPanel project={newProject} onSave={mockOnSave} />);
    
    await waitFor(() => {
      expect(screen.getByDisplayValue('Nuovo prompt aggiornato')).toBeInTheDocument();
    });
  });

  it('chiama onSave con prompt e stile aggiornati al blur del textarea', async () => {
    const user = userEvent.setup();
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    const textarea = screen.getByPlaceholderText(/Es\. viaggio/i);
    await user.type(textarea, ' - aggiunto testo');
    await user.tab(); // Blur
    
    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalledWith({
        user_prompt: 'Un viaggio emozionante tra amici - aggiunto testo',
        style_profile: 'cinematic',
      });
    });
  });

  it('chiama onSave quando si cambia lo stile', async () => {
    const user = userEvent.setup();
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    const select = screen.getByRole('combobox');
    await user.selectOptions(select, 'dynamic');
    
    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalledWith({
        style_profile: 'dynamic',
        user_prompt: 'Un viaggio emozionante tra amici',
      });
    });
  });

  it('chiama onSave quando si clicca il pulsante Salva', async () => {
    const user = userEvent.setup();
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    const button = screen.getByRole('button', { name: /Salva istruzioni/i });
    await user.click(button);
    
    expect(mockOnSave).toHaveBeenCalledWith({
      user_prompt: 'Un viaggio emozionante tra amici',
      style_profile: 'cinematic',
    });
  });

  it('disabilita i controlli quando busy è true', () => {
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} busy />);
    
    expect(screen.getByDisplayValue('Un viaggio emozionante tra amici')).toBeDisabled();
    expect(screen.getByRole('combobox')).toBeDisabled();
    expect(screen.getByRole('button', { name: /Salva istruzioni/i })).toBeDisabled();
  });

  it('mostra indicatore di salvataggio in corso', async () => {
    mockOnSave.mockImplementationOnce(() => new Promise(resolve => setTimeout(resolve, 100)));
    const user = userEvent.setup();
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    const button = screen.getByRole('button', { name: /Salva istruzioni/i });
    await user.click(button);
    
    expect(screen.getByText(/Salvataggio…/i)).toBeInTheDocument();
  });

  it('gestisce errore di salvataggio senza crashare', async () => {
    mockOnSave.mockRejectedValueOnce(new Error('Errore di rete'));
    const user = userEvent.setup();
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    const button = screen.getByRole('button', { name: /Salva istruzioni/i });
    await user.click(button);
    
    // Dopo l'errore, saved rimane false ma non crasha
    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalled();
    });
  });

  it('renderizza tutte le sezioni musicali', () => {
    render(<AIDirectorPanel project={mockProject} onSave={mockOnSave} />);
    
    // Verifica che tutte le sezioni della struttura musicale siano visibili (Intro, Verse, Chorus)
    expect(screen.getByText('Intro')).toBeInTheDocument();
    expect(screen.getByText('Verse')).toBeInTheDocument();
    expect(screen.getByText('Chorus')).toBeInTheDocument();
  });
});
