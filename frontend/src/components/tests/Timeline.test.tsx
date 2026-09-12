import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Timeline } from '../Timeline';

const mockOnReorder = vi.fn();
const mockOnToggleFill = vi.fn();
const mockOnDelete = vi.fn();
const mockOnReplace = vi.fn();

const mockMedia = [
  {
    id: 'media-1',
    source: 'local' as const,
    path: '/tmp/video.mp4',
    type: 'video' as const,
    orientation: 'landscape' as const,
    width: 1920,
    height: 1080,
    duration_sec: 5,
    order_index: 0,
    background_fill: 'blur' as const,
  },
];

describe('Timeline', () => {
  it('renders media duration', () => {
    render(
      <Timeline
        projectId="test-id"
        media={mockMedia}
        onReorder={mockOnReorder}
        onToggleFill={mockOnToggleFill}
        onDelete={mockOnDelete}
        onReplace={mockOnReplace}
      />
    );
    expect(screen.getByText('5.0s')).toBeInTheDocument();
  });

  it('renders total duration', () => {
    const media = [
      ...mockMedia,
      {
        ...mockMedia[0],
        id: 'media-2',
        duration_sec: 25,
        order_index: 1,
      },
    ];
    render(
      <Timeline
        projectId="test-id"
        media={media}
        onReorder={mockOnReorder}
        onToggleFill={mockOnToggleFill}
        onDelete={mockOnDelete}
        onReplace={mockOnReplace}
      />
    );
    expect(screen.getByText('30.0s')).toBeInTheDocument();
  });

  it('does not render when media is empty', () => {
    const { container } = render(
      <Timeline
        projectId="test-id"
        media={[]}
        onReorder={mockOnReorder}
        onToggleFill={mockOnToggleFill}
        onDelete={mockOnDelete}
        onReplace={mockOnReplace}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders correctly when the delete flow is available', () => {
    render(
      <Timeline
        projectId="test-id"
        media={mockMedia}
        onReorder={mockOnReorder}
        onToggleFill={mockOnToggleFill}
        onDelete={mockOnDelete}
        onReplace={mockOnReplace}
      />
    );
    window.confirm = vi.fn(() => true);
    expect(screen.getByText(/5\.0s/i)).toBeInTheDocument();
  });
});
