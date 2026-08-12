/**
 * A senha provisória aparece aqui e em nenhum outro lugar.
 *
 * Por isso o aviso é insistente. Mas a saída nunca é bloqueada: prender o gestor no modal
 * porque a cópia automática falhou seria pior do que ele fechar sem copiar — a cópia
 * depende de permissão do navegador e falha em contexto não seguro, coisa que ele não
 * controla. Quando falha, o texto continua na tela para seleção manual.
 */

import { AlertTriangle, Check, Copy } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Modal } from '@/components/base'

type Copia = 'nao-tentou' | 'copiado' | 'falhou'

export function SenhaProvisoria({
  nome,
  email,
  senha,
  aoFechar,
}: {
  nome: string
  email: string
  senha: string
  aoFechar: () => void
}) {
  const [copia, setCopia] = useState<Copia>('nao-tentou')

  const texto = `Acesso ao Gestão Solar\n\nE-mail: ${email}\nSenha provisória: ${senha}\n\nNo primeiro acesso o aplicativo pede para você criar uma senha própria.`

  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto)
      setCopia('copiado')
    } catch {
      setCopia('falhou')
    }
  }

  return (
    <Modal titulo="Acesso criado" aoFechar={aoFechar}>
      <p className="text-sm text-rotulo">
        Envie estes dados para <strong className="text-forte">{nome}</strong>. Esta senha
        aparece <strong className="text-forte">uma única vez</strong> — depois de fechar, só
        gerando outra.
      </p>

      <div className="mt-4 rounded-campo bg-afundado border border-borda p-4 select-text">
        <p className="text-xs text-rotulo">E-mail</p>
        <p className="mono text-sm text-forte">{email}</p>
        <p className="text-xs text-rotulo mt-3">Senha provisória</p>
        <p className="mono text-2xl font-semibold text-ambar tracking-wider">{senha}</p>
      </div>

      <button onClick={copiar} className="btn-primario w-full mt-4">
        {copia === 'copiado' ? <Check size={15} /> : <Copy size={15} />}
        {copia === 'copiado' ? 'Copiado' : 'Copiar mensagem pronta'}
      </button>

      <div className="mt-3">
        {copia === 'falhou' ? (
          <Aviso>
            O navegador não permitiu copiar sozinho. Selecione a senha acima e copie à mão
            antes de fechar.
          </Aviso>
        ) : copia === 'copiado' ? (
          <p className="flex items-center gap-2 text-sm text-ok">
            <Check size={15} />
            Mensagem copiada. Cole no WhatsApp ou no e-mail do cliente.
          </p>
        ) : (
          <p className="flex items-start gap-2 text-sm text-alerta">
            <AlertTriangle size={15} className="shrink-0 mt-0.5" />
            Copie ou anote antes de fechar — não dá para ver esta senha de novo.
          </p>
        )}
      </div>

      {/* Sempre disponível: o gestor pode ter anotado no papel, ou copiado à mão. */}
      <button onClick={aoFechar} className="btn-secundario w-full mt-3">
        {copia === 'copiado' ? 'Fechar' : 'Já anotei, fechar'}
      </button>
    </Modal>
  )
}
