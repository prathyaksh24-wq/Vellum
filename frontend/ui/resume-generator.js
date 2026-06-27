export function setupResumeGenerator() {
  const tool = document.querySelector('#prompt-tool');
  const button = document.querySelector('#generate-prompt');
  const output = document.querySelector('#prompt-output');
  if (!tool || !button || !output) return;

  async function generate() {
    output.value = 'Generating...';
    const response = await fetch('/api/resume-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: tool.value }),
    }).then((res) => res.json());
    output.value = response.prompt || response.error || '';
  }

  button.addEventListener('click', generate);
  generate();
}
