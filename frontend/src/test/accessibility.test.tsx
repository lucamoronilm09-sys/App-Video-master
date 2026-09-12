/**
 * Accessibility audit tests using axe-core
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';

expect.extend(toHaveNoViolations);

// Import components
import { UploadZone } from '../components/UploadZone';
import { PipelineProgress } from '../components/PipelineProgress';
import { AudioSection } from '../components/AudioSection';
import { ErrorPanel } from '../components/ErrorPanel';

describe('Accessibility Audit', () => {
  describe('UploadZone', () => {
    it('should have no accessibility violations', async () => {
      const { container } = render(
        <UploadZone projectId="test-123" onUploadComplete={() => {}} />
      );
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    });
  });

  describe('PipelineProgress', () => {
    it('should have no accessibility violations with empty log', async () => {
      const { container } = render(<PipelineProgress log={[]} />);
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    });

    it('should have no accessibility violations with progress', async () => {
      const log = [
        { stage: 'intake', status: 'completed' as const, message: 'Done' },
        { stage: 'normalizer', status: 'running' as const, message: 'Processing' },
      ];
      const { container } = render(<PipelineProgress log={log} />);
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    });
  });

  describe('AudioSection', () => {
    it('should have no accessibility violations when empty', async () => {
      const { container } = render(
        <AudioSection onUpload={async () => {}} />
      );
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    });
  });

  describe('ErrorPanel', () => {
    it('should have no accessibility violations with errors', async () => {
      const errors = [
        { title: 'Test Error', detail: 'Some details', hint: 'A hint' },
      ];
      const { container } = render(
        <ErrorPanel errors={errors} onClear={async () => {}} />
      );
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    });
  });
});
