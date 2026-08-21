import { useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  CircleCheck,
  CircleX,
  ExternalLink,
  FileCheck2,
  FileSearch,
  FileText,
  Gauge,
  Info,
  Lightbulb,
  ListChecks,
  Play,
  RotateCcw,
  ScanSearch,
  Sparkles,
  Target,
  Upload,
} from 'lucide-react';
import './index.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const formatLabel = (value = '') => value.replaceAll('_', ' ');

const GENERIC_ERROR = 'Could not evaluate the resume. Please try again.';

// The API returns one error envelope: { error: { code, message, request_id } }.
// Anything else -- a proxy HTML page, a truncated body, an older server -- must
// not reach the user as raw text, so it collapses to a generic message.
const readApiError = async (response) => {
  let body;
  try {
    body = await response.json();
  } catch {
    return GENERIC_ERROR;
  }

  const apiError = body?.error;
  if (typeof apiError?.message !== 'string' || !apiError.message) {
    return GENERIC_ERROR;
  }
  return apiError.code === 'internal_error' && apiError.request_id
    ? `${apiError.message} (reference ${apiError.request_id})`
    : apiError.message;
};

const formatFileSize = (bytes) => {
  if (!bytes) return '';
  return bytes < 1024 * 1024
    ? `${Math.ceil(bytes / 1024)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const getScoreColorClass = (score) => {
  if (score >= 80) return 'score-excellent';
  if (score >= 60) return 'score-good';
  return 'score-poor';
};

const getScoreLabel = (score) => {
  if (score >= 80) return 'Strong match';
  if (score >= 60) return 'Partial match';
  return 'Needs work';
};

function ScoreBadge({ score }) {
  const Icon = score >= 80 ? CheckCircle : score >= 60 ? AlertTriangle : AlertCircle;
  return (
    <div className={`score-badge ${getScoreColorClass(score)}`}>
      <Icon size={15} />
      <span>{getScoreLabel(score)}</span>
    </div>
  );
}

function PanelHeading({ icon: Icon, children, meta }) {
  return (
    <div className="panel-heading">
      <div><Icon size={15} /><h2>{children}</h2></div>
      {meta && <span>{meta}</span>}
    </div>
  );
}

const escapePattern = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function HighlightedText({ text, skill, alias }) {
  if (!text) return null;
  const label = formatLabel(skill);
  const terms = [alias, label, ...label.split(' ')].filter((term) => term && term.length > 2);
  const pattern = new RegExp(`(${terms.map(escapePattern).join('|')})`, 'gi');
  const normalized = new Set(terms.map((term) => term.toLowerCase()));

  return text.split(pattern).map((part, index) => (
    normalized.has(part.toLowerCase())
      ? <mark key={`${part}-${index}`}>{part}</mark>
      : part
  ));
}

function JobFitResults({ evaluation, profileTitle }) {
  const requirements = [...evaluation.required, ...evaluation.preferred];
  const matched = requirements.filter((item) => item.presence).length;
  const hasScore = evaluation.job_fit_score !== null;

  return (
    <div className="match-workspace">
      <div className="match-summary-strip">
        <div className="match-stat extracted"><ScanSearch size={14} /><strong>{requirements.length}</strong><span>requirements extracted</span></div>
        <div className="match-stat found"><CircleCheck size={14} /><strong>{matched}</strong><span>matches found</span></div>
        <div className="match-rate">
          <span>Match rate</span>
          <strong>{hasScore ? `${evaluation.job_fit_score}%` : 'N/A'}</strong>
        </div>
      </div>

      {hasScore ? (
        <div className="comparison-board">
          <div className="comparison-head">
            <span><FileText size={14} /> Job requirements</span>
            <small>{profileTitle}</small>
          </div>
          <div className="comparison-head"><FileSearch size={14} /><span>Resume evidence</span></div>

          {requirements.map((item, index) => (
            <div className="comparison-pair" key={`${item.skill_term}-${index}`}>
              <article className={`comparison-cell requirement-copy ${item.presence ? 'matched' : 'unmatched'}`}>
                <div className="comparison-label-row">
                  <span className={`bucket-label ${item.bucket}`}>{item.bucket}</span>
                  <strong>{formatLabel(item.skill_term)}</strong>
                </div>
                <p><HighlightedText text={item.raw_text} skill={item.skill_term} /></p>
                {(item.required_years || item.required_seniority) && (
                  <div className="qualifier-line">
                    {item.required_years && <span>{item.required_years}+ years</span>}
                    {item.required_seniority && <span>{item.required_seniority} level</span>}
                  </div>
                )}
              </article>

              <article className={`comparison-cell evidence-copy ${item.presence ? 'matched' : 'unmatched'}`}>
                <div className="evidence-status">
                  {item.presence ? <CircleCheck size={16} /> : <CircleX size={16} />}
                  <strong>{item.presence ? `${Math.round(item.match_score * 100)}% evidenced` : 'Not evidenced'}</strong>
                </div>
                <p>
                  {item.evidence_snippet
                    ? <HighlightedText text={item.evidence_snippet} skill={item.skill_term} alias={item.matched_alias} />
                    : 'No matching evidence found in the submitted resume.'}
                </p>
                {(item.claimed_years || item.claimed_seniority) && (
                  <div className="qualifier-line">
                    {item.claimed_years && <span>{item.claimed_years} years claimed</span>}
                    {item.claimed_seniority && <span>{item.claimed_seniority} level</span>}
                  </div>
                )}
              </article>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-evaluation">
          <Info size={17} />
          <span>No recognizable field requirements were found in the job description.</span>
        </div>
      )}
    </div>
  );
}

function ResumeQualityResults({ evaluation }) {
  return (
    <div className="result-sheet">
      <PanelHeading icon={Gauge} meta="Deterministic analysis">Resume quality</PanelHeading>
      <div className="results-header">
        <div className="total-score-block">
          <span className="score-kicker">Quality index</span>
          <div className="total-score" aria-label={`Resume quality score is ${evaluation.total_score} out of 100`}>
            {evaluation.total_score}<small>/100</small>
          </div>
        </div>
        <ScoreBadge score={evaluation.total_score} />
      </div>

      <div className="section-heading-row"><h3>Category breakdown</h3></div>
      {Object.entries(evaluation.categories).map(([category, data]) => (
        <details key={category}>
          <summary aria-label={`${formatLabel(category)} score: ${data.score} out of ${data.max}`}>
            <span className="summary-title">{formatLabel(category)}</span>
            <span className="summary-score">{data.score} / {data.max}<ChevronDown size={15} /></span>
          </summary>
          <div className="details-content"><pre>{JSON.stringify(data.details, null, 2)}</pre></div>
        </details>
      ))}
    </div>
  );
}

function GuidanceResults({ results }) {
  return (
    <div className="guidance-stack">
      <div className="result-sheet llm-panel">
        <PanelHeading icon={Sparkles} meta="Gemini supplement">Resume signals</PanelHeading>
        {results.llm_evaluation ? (
          <div className="llm-results">
            {Object.entries(results.llm_evaluation).map(([category, score]) => (
              <div key={category}><span>{formatLabel(category)}</span><strong>{score} / 100</strong></div>
            ))}
          </div>
        ) : (
          <div className="llm-note"><Info size={16} /><span>Gemini supplement unavailable. ({results.llm_evaluation_status})</span></div>
        )}
      </div>

      {results.job_fit_evaluation && (
        <div className="result-sheet llm-panel">
          <PanelHeading icon={Lightbulb} meta="Gemini supplement">Job-fit guidance</PanelHeading>
          {results.llm_job_fit_evaluation ? (
            <div className="guidance-content">
              <section><h3>Assessment</h3><p>{results.llm_job_fit_evaluation.overall_assessment}</p></section>
              <section>
                <h3>Gap explanations</h3>
                {results.llm_job_fit_evaluation.gap_explanations.length ? (
                  <ul>{results.llm_job_fit_evaluation.gap_explanations.map((item, index) => <li key={index}>{item}</li>)}</ul>
                ) : <p className="muted">No additional gaps identified.</p>}
              </section>
              <section>
                <h3>Phrasing suggestions</h3>
                {results.llm_job_fit_evaluation.phrasing_suggestions.length ? (
                  <ul>{results.llm_job_fit_evaluation.phrasing_suggestions.map((item, index) => <li key={index}>{item}</li>)}</ul>
                ) : <p className="muted">No phrasing changes suggested.</p>}
              </section>
            </div>
          ) : (
            <div className="llm-note"><Info size={16} /><span>Gemini guidance unavailable. ({results.llm_job_fit_evaluation_status})</span></div>
          )}
        </div>
      )}
    </div>
  );
}

function ProfilePreview({ preset, usesCustomJobDescription, jobDescription, includeJobFit }) {
  if (!includeJobFit) {
    return (
      <div className="empty-preview">
        <ListChecks size={34} />
        <span>Resume-only mode</span>
        <p>The selected field corpus will be used for the quality evaluation.</p>
      </div>
    );
  }

  if (usesCustomJobDescription) {
    return (
      <article className="profile-document custom-preview">
        <div className="document-index">CUSTOM PROFILE</div>
        <h2>Employer job description</h2>
        <div className="document-rule" />
        <p className={jobDescription ? 'job-copy' : 'empty-copy'}>
          {jobDescription || 'The custom job description will appear here as you enter it.'}
        </p>
      </article>
    );
  }

  if (!preset) {
    return <div className="empty-preview"><ScanSearch size={34} /><span>Loading profile index...</span></div>;
  }

  return (
    <article className="profile-document">
      <div className="document-index">PROFILE / {preset.id.toUpperCase()}</div>
      <h2>{preset.title}</h2>
      <p className="document-category">{preset.category}</p>
      <div className="document-rule" />
      <h3>Role summary</h3>
      <p>{preset.summary}</p>
      <details className="profile-details">
        <summary>Evaluation brief <ChevronDown size={15} /></summary>
        <pre>{preset.description}</pre>
      </details>
      <div className="source-register">
        <span>Source register</span>
        {preset.sources.map((source) => (
          <a href={source.url} target="_blank" rel="noreferrer" key={source.url}>
            {source.occupation_code ? `${source.organization} ${source.occupation_code}` : source.organization}
            <ExternalLink size={12} />
          </a>
        ))}
      </div>
    </article>
  );
}

function App() {
  const [fields, setFields] = useState([]);
  const [selectedField, setSelectedField] = useState('');
  const [jobPresets, setJobPresets] = useState([]);
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [file, setFile] = useState(null);
  const [includeJobFit, setIncludeJobFit] = useState(true);
  const [jobDescription, setJobDescription] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState(null);
  const [resultView, setResultView] = useState('overview');
  const fileInputRef = useRef(null);
  const selectedPreset = jobPresets.find((preset) => preset.id === selectedPresetId);
  const usesCustomJobDescription = selectedPresetId === 'custom';
  const activeJobDescription = selectedPreset?.description || jobDescription.trim();

  useEffect(() => {
    Promise.all([fetch(`${API_BASE_URL}/fields`), fetch(`${API_BASE_URL}/job-presets`)])
      .then(async ([fieldsResponse, presetsResponse]) => {
        if (!fieldsResponse.ok || !presetsResponse.ok) throw new Error('Could not load evaluation profiles.');
        return Promise.all([fieldsResponse.json(), presetsResponse.json()]);
      })
      .then(([fieldsData, presetsData]) => {
        setFields(fieldsData.fields);
        setJobPresets(presetsData.presets);
        const firstPreset = presetsData.presets[0];
        if (firstPreset) {
          setSelectedPresetId(firstPreset.id);
          setSelectedField(firstPreset.field);
        } else if (fieldsData.fields.length > 0) {
          setSelectedPresetId('custom');
          setSelectedField(fieldsData.fields[0]);
        }
      })
      .catch(() => setError('Could not load evaluation profiles. Ensure the backend is running.'));
  }, []);

  const handlePresetChange = (event) => {
    const presetId = event.target.value;
    setSelectedPresetId(presetId);
    const preset = jobPresets.find((item) => item.id === presetId);
    if (preset) setSelectedField(preset.field);
  };

  const acceptFile = (candidate) => {
    const name = candidate.name.toLowerCase();
    if (name.endsWith('.pdf') || name.endsWith('.docx')) {
      setFile(candidate);
      setError('');
    } else {
      setError('Only .pdf and .docx files are supported.');
    }
  };

  const handleDrag = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(event.type === 'dragenter' || event.type === 'dragover');
  };

  const handleDrop = (event) => {
    handleDrag(event);
    setDragActive(false);
    if (event.dataTransfer.files?.[0]) acceptFile(event.dataTransfer.files[0]);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!file) {
      setError('Please select a resume first.');
      return;
    }
    if (includeJobFit && !activeJobDescription) {
      setError('Select a job profile, add a custom description, or turn off job-fit analysis.');
      return;
    }

    setIsLoading(true);
    setError('');
    setResults(null);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('field', selectedField);
    if (includeJobFit) formData.append('jd_text', activeJobDescription);

    try {
      const response = await fetch(`${API_BASE_URL}/evaluate`, { method: 'POST', body: formData });
      if (!response.ok) throw new Error(await readApiError(response));
      const data = await response.json();
      setResults(data);
      setResultView(includeJobFit ? 'evidence' : 'overview');
    } catch (requestError) {
      // A network failure (backend down, CORS, DNS) has no response to read.
      setError(requestError.message || GENERIC_ERROR);
    } finally {
      setIsLoading(false);
    }
  };

  const resetEvaluation = () => {
    setResults(null);
    setFile(null);
    setJobDescription('');
    setError('');
    setResultView('overview');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const qualityScore = results?.heuristic_evaluation.total_score;
  const fitScore = results?.job_fit_evaluation?.job_fit_score;

  return (
    <main className="app-frame">
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {isLoading ? 'Evaluating resume and job fit, please wait.' : ''}
        {error ? `Error: ${error}` : ''}
        {results ? 'Evaluation complete. Results are displayed.' : ''}
      </div>

      <header className="app-header">
        <div className="header-identity">
          <span className="system-label"><FileSearch size={14} /> RESUME INTELLIGENCE / MVP2</span>
          <h1>Resume Evaluator</h1>
          <span className="mode-line">// {results ? 'ANALYSIS MODE' : 'INPUT MODE'}</span>
        </div>
        <div className="header-status">
          <span><i /> LOCAL API</span>
          {results && (
            <button type="button" className="utility-button" onClick={resetEvaluation}>
              <RotateCcw size={14} /> Reset
            </button>
          )}
        </div>
      </header>

      <div className="workspace">
        <aside className="control-pane">
          {!results ? (
            <form onSubmit={handleSubmit} className="evaluation-form">
              <PanelHeading icon={ScanSearch} meta="01 / Setup">Evaluation panel</PanelHeading>
              {error && <div className="error-message"><AlertCircle size={18} /><span>{error}</span></div>}

              <fieldset className="control-group">
                <legend>Target configuration</legend>
                <div className="form-group">
                  <label htmlFor="field-select">Target field</label>
                  <select id="field-select" value={selectedField} onChange={(event) => setSelectedField(event.target.value)} disabled={isLoading || fields.length === 0 || (includeJobFit && Boolean(selectedPreset))}>
                    {fields.map((field) => <option key={field} value={field}>{formatLabel(field).toUpperCase()}</option>)}
                  </select>
                </div>

                <label className="check-control">
                  <input type="checkbox" checked={includeJobFit} onChange={(event) => setIncludeJobFit(event.target.checked)} disabled={isLoading} />
                  <span className="check-box" aria-hidden="true">{includeJobFit && <CircleCheck size={17} />}</span>
                  <span><strong>Job-fit analysis</strong><small>Compare resume evidence to a role profile</small></span>
                </label>

                {includeJobFit && (
                  <div className="form-group profile-select">
                    <label htmlFor="job-profile">Job profile</label>
                    <select id="job-profile" value={selectedPresetId} onChange={handlePresetChange} disabled={isLoading || jobPresets.length === 0}>
                      {jobPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.title}</option>)}
                      <option value="custom">Custom job description</option>
                    </select>
                  </div>
                )}

                {includeJobFit && usesCustomJobDescription && (
                  <div className="form-group custom-job-description">
                    <div className="label-row">
                      <label htmlFor="job-description">Job description</label>
                      <span>{jobDescription.length.toLocaleString()} / 20,000</span>
                    </div>
                    <textarea id="job-description" value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} maxLength={20000} rows={8} placeholder="Paste the complete job description..." disabled={isLoading} />
                  </div>
                )}
              </fieldset>

              <fieldset className="control-group upload-group">
                <legend>Resume source</legend>
                <div className={`file-drop-area ${dragActive ? 'drag-active' : ''} ${file ? 'has-file' : ''}`} onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop} onClick={() => fileInputRef.current?.click()} onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    fileInputRef.current?.click();
                  }
                }} tabIndex={0} role="button" aria-label="Upload resume file">
                  <input ref={fileInputRef} type="file" className="file-input" onChange={(event) => event.target.files?.[0] && acceptFile(event.target.files[0])} accept=".pdf,.docx" disabled={isLoading} tabIndex={-1} />
                  {file ? <FileCheck2 size={28} /> : <Upload size={28} />}
                  {file ? (
                    <div className="selected-file"><strong>{file.name}</strong><span>{formatFileSize(file.size)} / READY</span></div>
                  ) : (
                    <div><strong>Click or drag file</strong><span>PDF, DOCX / MAX 5 MB</span></div>
                  )}
                </div>
              </fieldset>

              <button type="submit" className="primary-button" disabled={isLoading || !file} aria-busy={isLoading}>
                {isLoading ? <span className="loading-block" /> : <Play size={16} />}
                {isLoading ? 'Processing resume...' : 'Run evaluation'}
              </button>
            </form>
          ) : (
            <div className="run-index">
              <PanelHeading icon={resultView === 'evidence' ? Target : FileCheck2} meta="Complete">
                {resultView === 'evidence' ? 'JD match analysis' : 'Run index'}
              </PanelHeading>
              <div className="run-file">
                <span>Source file</span>
                <strong>{file?.name}</strong>
                <small>{formatFileSize(file?.size)}</small>
              </div>
              <dl className="run-metadata">
                <div><dt>Target field</dt><dd>{formatLabel(selectedField)}</dd></div>
                <div><dt>Profile</dt><dd>{selectedPreset?.title || (includeJobFit ? 'Custom description' : 'Resume only')}</dd></div>
                <div><dt>Quality index</dt><dd>{qualityScore} / 100</dd></div>
                {fitScore !== undefined && fitScore !== null && <div><dt>Evidence match</dt><dd>{fitScore} / 100</dd></div>}
              </dl>
              {results.job_fit_evaluation && (
                <div className="analysis-index">
                  <div>
                    <span>Matched evidence</span>
                    <strong>{[...results.job_fit_evaluation.required, ...results.job_fit_evaluation.preferred].filter((item) => item.presence).length}</strong>
                  </div>
                  <div>
                    <span>Evidence gaps</span>
                    <strong>{results.job_fit_evaluation.missing_required.length + results.job_fit_evaluation.missing_preferred.length}</strong>
                  </div>
                </div>
              )}
              {results.job_fit_evaluation?.missing_required.length > 0 && (
                <div className="side-gaps">
                  <span>Required gaps</span>
                  <div>{results.job_fit_evaluation.missing_required.map((skill) => <b key={skill}>{formatLabel(skill)}</b>)}</div>
                </div>
              )}
              <button type="button" className="secondary-button" onClick={resetEvaluation}><RotateCcw size={15} />New evaluation</button>
            </div>
          )}
        </aside>

        <section className="display-pane">
          <div className="display-toolbar">
            {results ? (
              <nav className="view-tabs" aria-label="Evaluation result views">
                <button type="button" className={resultView === 'overview' ? 'active' : ''} onClick={() => setResultView('overview')}><Gauge size={13} />Overview</button>
                {results.job_fit_evaluation && <button type="button" className={resultView === 'evidence' ? 'active' : ''} onClick={() => setResultView('evidence')}><Target size={13} />Evidence</button>}
                <button type="button" className={resultView === 'guidance' ? 'active' : ''} onClick={() => setResultView('guidance')}><Sparkles size={13} />Guidance</button>
              </nav>
            ) : (
              <span className="toolbar-title"><FileText size={13} /> Profile brief</span>
            )}
            <span className="display-state"><i /> {isLoading ? 'PROCESSING' : results ? 'RUN COMPLETE' : 'SYSTEM READY'}</span>
          </div>

          <div className={`display-canvas ${results ? 'results-canvas' : ''} ${resultView === 'evidence' ? 'comparison-canvas' : ''}`}>
            {!results && <ProfilePreview preset={selectedPreset} usesCustomJobDescription={usesCustomJobDescription} jobDescription={jobDescription} includeJobFit={includeJobFit} />}
            {results && resultView === 'overview' && <ResumeQualityResults evaluation={results.heuristic_evaluation} />}
            {results && resultView === 'evidence' && results.job_fit_evaluation && <JobFitResults evaluation={results.job_fit_evaluation} profileTitle={selectedPreset?.title} />}
            {results && resultView === 'guidance' && <GuidanceResults results={results} />}
          </div>
        </section>
      </div>

      <footer className="status-bar">
        <span><ScanSearch size={12} /> RESUME EVALUATOR MODULE</span>
        <div><span><i /> {results ? 'EVALUATION COMPLETE' : 'READY'}</span><span>{formatLabel(selectedField || 'loading')}</span><span>V2.0</span></div>
      </footer>
    </main>
  );
}

export default App;
