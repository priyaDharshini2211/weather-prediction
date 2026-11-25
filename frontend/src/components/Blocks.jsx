import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

const COLORS = ['#2563eb', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#64748b'];
const AXIS_TICK = { fill: 'var(--muted)', fontSize: 12 };
const TOOLTIP_STYLE = { background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text)' };
const LINE_COLORS = { max: '#ef4444', avg: '#f59e0b', min: '#2563eb' };

function Metrics({ block }) {
  return (
    <section className="block">
      <h4>{block.title}</h4>
      <div className="metrics">
        {block.items.map((item) => (
          <div className="metric" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function DataTable({ block }) {
  return (
    <section className="block">
      <h4>{block.title}</h4>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>{block.columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {block.rows.map((row, i) => (
              <tr key={i}>{row.map((cell, j) => <td key={j}>{cell ?? 'n/a'}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Chart({ block }) {
  const { chart, data, series, x_key: xKey, unit } = block;
  const tooltipFormatter = (value) => (value === null ? 'n/a' : `${value} ${unit ?? ''}`);

  return (
    <section className="block">
      <h4>{block.title}</h4>
      <div className="chart">
        <ResponsiveContainer width="100%" height={260}>
          {chart === 'line' ? (
            <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey={xKey} tickFormatter={(d) => d.slice(5)} tick={AXIS_TICK} stroke="var(--border)" />
              <YAxis unit={` ${unit ?? ''}`} width={56} tick={AXIS_TICK} stroke="var(--border)" />
              <Tooltip formatter={tooltipFormatter} contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ color: 'var(--text)' }} />
              {series.map((s) => (
                <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={LINE_COLORS[s.key] ?? COLORS[0]} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              ))}
            </LineChart>
          ) : chart === 'bar' ? (
            <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey={xKey} tickFormatter={(d) => d.slice(5)} tick={AXIS_TICK} stroke="var(--border)" />
              <YAxis unit={` ${unit ?? ''}`} width={56} tick={AXIS_TICK} stroke="var(--border)" />
              <Tooltip formatter={tooltipFormatter} contentStyle={TOOLTIP_STYLE} />
              {series.map((s) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={COLORS[0]} radius={[4, 4, 0, 0]} />)}
            </BarChart>
          ) : (
            <PieChart>
              <Tooltip formatter={tooltipFormatter} contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ color: 'var(--text)' }} />
              <Pie data={data} dataKey="value" nameKey={xKey} outerRadius={90} label={(entry) => `${entry.value}`}>
                {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
            </PieChart>
          )}
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function Sources({ block }) {
  const isWeb = block.kind === 'web';
  return (
    <details className={`block sources ${isWeb ? 'sources-web' : ''}`} open={isWeb}>
      <summary>{block.title} ({block.items.length})</summary>
      <ul>
        {block.items.map((item) => (
          <li key={item.title}>
            {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : <strong>{item.title}</strong>}
            {item.snippet && <p>{item.snippet}</p>}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Notice({ block }) {
  return <div className={`notice notice-${block.level}`}>{block.text}</div>;
}

const RENDERERS = { metrics: Metrics, table: DataTable, chart: Chart, sources: Sources, notice: Notice };

export default function Blocks({ blocks }) {
  return (
    <>
      {blocks.map((block, i) => {
        const Renderer = RENDERERS[block.type];
        return Renderer ? <Renderer key={i} block={block} /> : null;
      })}
    </>
  );
}
