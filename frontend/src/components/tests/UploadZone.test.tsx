import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { UploadZone } from '../UploadZone';

// Mock del modulo api
vi.mock('@/lib/api', () => ({
  uploadMedia: vi.fn(),
}));

describe('UploadZone', () => {
  const mockOnUploadComplete = vi.fn();

  it('renders without crashing', () => {
    render(<UploadZone projectId="test-id" onUploadComplete={mockOnUploadComplete} />);
    const zone = screen.getByRole('button');
    expect(zone).toBeInTheDocument();
  });

  it('displays upload instructions when not uploading', () => {
    render(<UploadZone projectId="test-id" onUploadComplete={mockOnUploadComplete} />);
    expect(screen.getByText(/Trascina foto\/video qui/i)).toBeInTheDocument();
  });

  it('shows upload control when ready', () => {
    render(<UploadZone projectId="test-id" onUploadComplete={mockOnUploadComplete} />);
    const zone = screen.getByRole('button');
    expect(zone).toBeInTheDocument();
  });
});
