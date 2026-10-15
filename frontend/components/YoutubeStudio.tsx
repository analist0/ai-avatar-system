'use client'

import { useEffect, useState } from 'react'
import { Heebo } from 'next/font/google'
import { api } from '@/lib/api'
import type { YoutubeEngine, YoutubeProject } from '@/lib/types'
import { toast } from 'react-hot-toast'
import { Clapperboard, Download, Loader2, Video } from 'lucide-react'

const heebo = Heebo({ subsets: ['hebrew', 'latin'], weight: ['400', '500', '700'] })

const SAMPLE = `# למה השינה חשובה

## פתיח
אם אתם קמים עייפים, הבעיה היא כמעט אף פעם לא רק שעת השינה.

## מה קורה בלילה
המוח מנקה את עצמו בשעות העמוקות. בלי זה, הזיכרון של היום למחרת נשאר מטושטש.

[pause 0.4]
## מה לעשות הערב
כבו מסכים חצי שעה לפני השינה, והחשיכו את החדר.
`

const ASPECTS = [
  { id: 'landscape', label: 'יוטיוב 16:9', hint: '1920×1080' },
  { id: 'portrait', label: 'שורטס 9:16', hint: '1080×1920' },
  { id: 'square', label: 'ריבוע 1:1', hint: '1080×1080' },
] as const

const STATUS_LABEL: Record<string, string> = {
  builtin: 'בשימוש',
  missing: 'המשקולות לא מותקנות',
  refused: 'נדחה',
  not_integrated: 'לא חובר',
}

interface Props {
  avatarId: string | null
  onNeedAvatar: () => void
}

export function YoutubeStudio({ avatarId, onNeedAvatar }: Props) {
  const [engines, setEngines] = useState<YoutubeEngine[]>([])
  const [showEngines, setShowEngines] = useState(false)
  const [title, setTitle] = useState('')
  const [script, setScript] = useState(SAMPLE)
  const [language, setLanguage] = useState('he')
  const [aspect, setAspect] = useState<'landscape' | 'portrait' | 'square'>('landscape')
  const [burn, setBurn] = useState(false)
  const [project, setProject] = useState<YoutubeProject | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.listYoutubeEngines().then(setEngines).catch(() => {
      toast.error('לא הצלחתי לטעון את רשימת המנועים')
    })
  }, [])

  const projectId = project?.id
  const projectStatus = project?.status
  useEffect(() => {
    if (!projectId || projectStatus !== 'rendering') return
    const timer = setInterval(async () => {
      try {
        const next = await api.getYoutubeProject(projectId)
        setProject(next)
        if (next.status === 'ready') toast.success('הסרטון מוכן')
        if (next.status === 'failed') toast.error(next.error || 'הרינדור נכשל')
      } catch {
        /* keep polling; a single blip should not kill the job */
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [projectId, projectStatus])

  const rtl = language === 'he' || language === 'ar'

  const render = async () => {
    if (!avatarId) {
      onNeedAvatar()
      return
    }
    setBusy(true)
    try {
      const created = await api.createYoutubeProject({
        avatar_id: avatarId,
        title,
        script,
        language,
        aspect,
        burn_captions: burn,
      })
      const started = await api.renderYoutubeProject(created.id)
      setProject(started)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'לא הצלחתי להתחיל רינדור')
    } finally {
      setBusy(false)
    }
  }

  const meta = project?.project_metadata
  const rendering = project?.status === 'rendering' || busy

  return (
    <div className={`${heebo.className} max-w-6xl mx-auto px-6 py-10`} dir="rtl">
      <div className="mb-8 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black gradient-text mb-2">אולפן יוטיוב</h1>
          <p className="text-gray-400 max-w-2xl">
            תסריט נכנס, סרטון של האווטר יוצא: MP4, כתוביות, ופרקים. התנועה על תמונה
            סטטית היא נשימה וסחיפה — ליפ-סינק אמיתי רק כש-MuseTalk מותקן.
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={() => setShowEngines(v => !v)}>
          <Clapperboard size={16} />
          מאיפה זה בא
        </button>
      </div>

      {showEngines && (
        <div className="mb-8 grid gap-3">
          {engines.map(engine => (
            <article key={engine.id} dir="ltr" className="rounded-2xl border border-white/10 bg-surface-800/80 p-4 text-left">
              <div className="flex items-center justify-between gap-3 mb-2">
                <div>
                  <h2 className="font-bold text-white">{engine.source}</h2>
                  <p className="text-xs text-gray-500">{engine.role} · {engine.license}</p>
                </div>
                <span className={`text-xs px-2 py-1 rounded-full border ${
                  engine.status === 'builtin'
                    ? 'border-emerald-500/40 text-emerald-300'
                    : engine.status === 'refused'
                      ? 'border-rose-500/40 text-rose-300'
                      : 'border-amber-500/40 text-amber-200'
                }`}>
                  {STATUS_LABEL[engine.status] || engine.status}
                </span>
              </div>
              <p className="text-sm text-gray-300 mb-1"><span className="text-gray-500">לקחנו: </span>{engine.taken}</p>
              <p className="text-sm text-gray-400"><span className="text-gray-500">השארנו בחוץ: </span>{engine.left_out}</p>
            </article>
          ))}
        </div>
      )}

      {!avatarId && (
        <div className="mb-6 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 flex items-center justify-between gap-4">
          <p className="text-amber-100 text-sm">בחרו אווטר קודם. הסרטון נבנה מהתמונה והקול שלו.</p>
          <button type="button" className="btn-primary" onClick={onNeedAvatar}>לבחירת אווטר</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3 space-y-4">
          <label className="block">
            <span className="text-sm text-gray-400">כותרת (אופציונלי — אחרת נלקחת מהשורה שמתחילה ב־#)</span>
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              className="mt-1 w-full rounded-xl bg-surface-800 border border-white/10 px-4 py-3 text-white"
              placeholder="למה השינה חשובה"
            />
          </label>
          <label className="block">
            <span className="text-sm text-gray-400">תסריט. ## הוא פרק, שורה ריקה מפצלת פסקה, [pause 0.4] הוא שקט.</span>
            <textarea
              value={script}
              onChange={e => setScript(e.target.value)}
              dir={rtl ? 'rtl' : 'ltr'}
              rows={16}
              className="mt-1 w-full rounded-xl bg-surface-800 border border-white/10 px-4 py-3 text-white leading-relaxed"
            />
          </label>
        </div>

        <div className="lg:col-span-2 space-y-4">
          <div className="rounded-2xl border border-white/10 bg-surface-800/80 p-4 space-y-3">
            <label className="block text-sm text-gray-400">
              שפה
              <select
                value={language}
                onChange={e => setLanguage(e.target.value)}
                className="mt-1 w-full rounded-xl bg-surface-900 border border-white/10 px-3 py-2 text-white"
              >
                <option value="he">עברית</option>
                <option value="en">English</option>
                <option value="ar">العربية</option>
                <option value="ru">Русский</option>
                <option value="es">Español</option>
                <option value="fr">Français</option>
              </select>
            </label>
            <div className="grid grid-cols-1 gap-2">
              {ASPECTS.map(option => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setAspect(option.id)}
                  className={`text-right rounded-xl px-3 py-2 border ${
                    aspect === option.id
                      ? 'border-primary-500 bg-primary-500/10 text-white'
                      : 'border-white/10 text-gray-300'
                  }`}
                >
                  <div className="font-medium">{option.label}</div>
                  <div className="text-xs text-gray-500">{option.hint}</div>
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-300">
              <input type="checkbox" checked={burn} onChange={e => setBurn(e.target.checked)} />
              לצרוב כתוביות על הווידאו (ה-SRT תמיד נוצר)
            </label>
            <button type="button" className="btn-primary w-full" disabled={rendering || !avatarId} onClick={render}>
              {rendering ? <Loader2 size={16} className="animate-spin" /> : <Video size={16} />}
              {rendering ? `מרנדר${project ? ` ${project.progress}%` : ''}` : 'להפיק סרטון'}
            </button>
            {project?.status === 'rendering' && (
              <div className="h-1.5 rounded-full bg-surface-600 overflow-hidden">
                <div className="h-full bg-primary-500" style={{ width: `${project.progress}%` }} />
              </div>
            )}
          </div>
        </div>
      </div>

      {project && (
        <section className="mt-6 rounded-2xl border border-white/10 bg-surface-800/80 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-bold">{project.title}</h2>
            <span className="text-xs text-gray-400">{project.status}</span>
          </div>
          {project.status === 'failed' && (
            <p className="text-sm text-rose-300">{project.error}</p>
          )}
          {project.video_url && project.status === 'ready' && (
            <video src={project.video_url} controls className="w-full max-h-[70vh] rounded-xl bg-black" />
          )}
          {meta?.warnings && meta.warnings.length > 0 && (
            <ul className="text-sm text-amber-200/90 space-y-1">
              {meta.warnings.map(warning => <li key={warning}>{warning}</li>)}
            </ul>
          )}
          {project.status === 'ready' && (
            <div className="flex flex-wrap gap-2">
              {project.video_url && <FileLink href={project.video_url} label="MP4" />}
              {project.srt_url && <FileLink href={project.srt_url} label="כתוביות SRT" />}
              {project.chapters_url && <FileLink href={project.chapters_url} label="פרקים" />}
              {project.description_url && <FileLink href={project.description_url} label="תיאור" />}
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function FileLink({ href, label }: { href: string; label: string }) {
  return (
    <a href={href} className="btn-secondary text-sm" download>
      <Download size={14} />
      {label}
    </a>
  )
}
