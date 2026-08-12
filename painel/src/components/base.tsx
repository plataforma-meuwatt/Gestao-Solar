/**
 * Peças que todas as telas usam.
 *
 * Estão juntas porque se citam entre si e porque a coerência entre elas é o que faz o
 * painel parecer um sistema, e não seis telas parecidas.
 */

import { AlertTriangle, Check, Loader2, X } from 'lucide-react'
import type { ReactNode } from 'react'

/* ------------------------------------------------------------------ layout */

export function Pagina({
  titulo,
  apoio,
  acao,
  children,
}: {
  titulo: string
  apoio?: string
  acao?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="max-w-5xl">
      <header className="flex items-start gap-4 mb-6">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-forte tracking-tight">{titulo}</h1>
          {apoio ? <p className="text-sm text-rotulo mt-1 max-w-[60ch]">{apoio}</p> : null}
        </div>
        {acao ? <div className="ml-auto shrink-0">{acao}</div> : null}
      </header>
      {children}
    </div>
  )
}

export function Cartao({
  titulo,
  acao,
  children,
  className = '',
}: {
  titulo?: string
  acao?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`cartao ${className}`}>
      {titulo || acao ? (
        <header className="flex items-center gap-3 px-5 pt-4 pb-3">
          {titulo ? <h2 className="rotulo-secao">{titulo}</h2> : null}
          {acao ? <div className="ml-auto">{acao}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  )
}

/* ------------------------------------------------------------------ estado */

export type Tom = 'ok' | 'alerta' | 'parado' | 'sem-dados' | 'tempo-ruim'

const TINTA: Record<Tom, string> = {
  ok: 'text-ok bg-ok/10 border-ok/30',
  alerta: 'text-alerta bg-alerta/10 border-alerta/30',
  parado: 'text-parado bg-parado/10 border-parado/30',
  'sem-dados': 'text-sem-dados bg-sem-dados/10 border-sem-dados/30',
  'tempo-ruim': 'text-tempo-ruim bg-tempo-ruim/10 border-tempo-ruim/30',
}

export function Selo({ tom, children }: { tom: Tom; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-campo border px-2.5 py-1
                  text-[11px] font-semibold ${TINTA[tom]}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {children}
    </span>
  )
}

export function Carregando({ texto = 'Carregando…' }: { texto?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-fraco py-10 justify-center">
      <Loader2 size={16} className="animate-spin" />
      {texto}
    </div>
  )
}

export function Vazio({ titulo, descricao, acao }: { titulo: string; descricao?: string; acao?: ReactNode }) {
  return (
    <div className="text-center py-14 px-6">
      <p className="text-forte font-semibold">{titulo}</p>
      {descricao ? <p className="text-sm text-rotulo mt-1.5 max-w-[46ch] mx-auto">{descricao}</p> : null}
      {acao ? <div className="mt-5 inline-flex">{acao}</div> : null}
    </div>
  )
}

export function Erro({ children, className = '' }: { children: ReactNode; className?: string }) {
  if (!children) return null
  return (
    <div
      className={`flex items-start gap-2.5 rounded-campo border border-parado/30
                  bg-parado/10 px-3.5 py-3 text-sm text-parado ${className}`}
      role="alert"
    >
      <AlertTriangle size={16} className="shrink-0 mt-0.5" />
      <span>{children}</span>
    </div>
  )
}

export function Aviso({ children }: { children: ReactNode }) {
  return (
    <div
      className="flex items-start gap-2.5 rounded-campo border border-alerta/30
                 bg-alerta/10 px-3.5 py-3 text-sm text-alerta"
    >
      <AlertTriangle size={16} className="shrink-0 mt-0.5" />
      <span>{children}</span>
    </div>
  )
}

/* ------------------------------------------------------------------ campos */

export function Campo({
  rotulo,
  nota,
  erro,
  ...props
}: {
  rotulo: string
  nota?: string
  erro?: string
} & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = props.id ?? `campo-${rotulo.toLowerCase().replace(/\W+/g, '-')}`
  return (
    <div>
      <label className="rotulo-campo" htmlFor={id}>
        {rotulo}
      </label>
      <input
        {...props}
        id={id}
        className={`campo ${erro ? 'border-parado' : ''} ${props.className ?? ''}`}
      />
      {erro ? <p className="text-xs text-parado mt-1.5">{erro}</p> : null}
      {nota && !erro ? <p className="text-xs text-fraco mt-1.5">{nota}</p> : null}
    </div>
  )
}

export function Seletor({
  rotulo,
  children,
  ...props
}: { rotulo: string; children: ReactNode } & React.SelectHTMLAttributes<HTMLSelectElement>) {
  const id = props.id ?? `sel-${rotulo.toLowerCase().replace(/\W+/g, '-')}`
  return (
    <div>
      <label className="rotulo-campo" htmlFor={id}>
        {rotulo}
      </label>
      <select {...props} id={id} className={`campo ${props.className ?? ''}`}>
        {children}
      </select>
    </div>
  )
}

/* ------------------------------------------------------------------- modal */

export function Modal({
  titulo,
  aoFechar,
  children,
  largura = 'max-w-lg',
}: {
  titulo: string
  aoFechar: () => void
  children: ReactNode
  largura?: string
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
      onClick={aoFechar}
      role="dialog"
      aria-modal="true"
      aria-label={titulo}
    >
      <div
        className={`w-full ${largura} bg-[#090E26] border border-borda rounded-card
                    max-h-[88vh] overflow-y-auto`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center gap-3 px-5 py-4 border-b border-borda sticky top-0 bg-[#090E26]">
          <h2 className="text-lg font-bold text-forte">{titulo}</h2>
          <button
            onClick={aoFechar}
            className="ml-auto text-fraco hover:text-forte"
            aria-label="Fechar"
          >
            <X size={18} />
          </button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ passos */

export function Passos({ atual, nomes }: { atual: number; nomes: string[] }) {
  return (
    <ol className="flex items-center gap-2 mb-6">
      {nomes.map((nome, i) => {
        const feito = i < atual
        const agora = i === atual
        return (
          <li key={nome} className="flex items-center gap-2">
            <span
              className={`w-6 h-6 rounded-full grid place-items-center text-[11px] font-semibold
                ${agora ? 'bg-ambar text-fundo' : feito ? 'bg-ok/20 text-ok border border-ok/40' : 'border border-borda text-fraco'}`}
            >
              {feito ? <Check size={12} /> : i + 1}
            </span>
            <span className={`text-xs ${agora ? 'text-forte font-semibold' : 'text-fraco'}`}>
              {nome}
            </span>
            {i < nomes.length - 1 ? <span className="w-6 h-px bg-borda" /> : null}
          </li>
        )
      })}
    </ol>
  )
}
