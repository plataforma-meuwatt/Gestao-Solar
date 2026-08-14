/**
 * Relatórios publicados para as usinas desta pessoa.
 *
 * A filtragem por escopo acontece no BFF, e não aqui: o Portal do Cliente do meuWatt
 * devolve as usinas todas quando quem chama é administrador — e o BFF chama com um token
 * que costuma ser. Ver `bff/app/api/v1/documents.py`.
 */

import { baseURL } from '@/lib/api'
import { fetchWithCache, type Leitura } from '@/lib/cache'

export type ArquivoDoDocumento = {
  /** `geracao` (Relatório de Geração) ou `paradas` (Anexo de Paradas). */
  tipo: string
  nome: string
}

export type Documento = {
  id: number
  nome: string
  usina: string
  /** `DIÁRIO` · `SEMANAL` · `MENSAL` · `ANUAL` — vocabulário do meuWatt. */
  periodo: string
  de: string
  ate: string
  publicado_em: string
  arquivos: ArquivoDoDocumento[]
}

export type DocumentosOut = {
  documentos: Documento[]
  aviso: string | null
}

export function useDocumentos(): Leitura<DocumentosOut> {
  return fetchWithCache<DocumentosOut>('documents')
}

/** Endereço do PDF, para o `PdfViewer` abrir dentro do app. */
export function urlDoArquivo(documentoId: number, tipo = 'geracao'): string {
  return `${baseURL}/api/v1/documents/${documentoId}/file?tipo=${encodeURIComponent(tipo)}`
}
