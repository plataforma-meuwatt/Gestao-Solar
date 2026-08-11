/**
 * Início. Esqueleto da Fase 0 — a estrutura da tela e os componentes estão de pé; os
 * dados entram na Fase 1, por `GET /api/v1/home`.
 */

import { Text } from 'react-native'

import { Card } from '@/components/Card'
import { Kpi } from '@/components/Kpi'
import { TelaColapsavel } from '@/components/TelaColapsavel'
import { dataPorExtenso } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { tipo } from '@/theme/tokens'

function saudacao(hora = new Date().getHours()): string {
  if (hora < 12) return 'Bom dia'
  if (hora < 18) return 'Boa tarde'
  return 'Boa noite'
}

export default function Inicio() {
  const usuario = useAuth((s) => s.usuario)
  const primeiroNome = usuario?.nome.split(' ')[0] ?? ''

  return (
    <TelaColapsavel
      titulo={`${saudacao()}, ${primeiroNome}`}
      subtitulo={dataPorExtenso(new Date().toISOString())}
    >
      <Card titulo="Agora">
        <Kpi rotulo="Potência" valor="—" unidade="kW" grande />
        <Text style={tipo.rotulo}>Aguardando dados do BFF</Text>
      </Card>

      <Card titulo="meuWatt">
        <Text style={tipo.corpo}>Geração do mês entra na Fase 2.</Text>
      </Card>

      <Card titulo="meuPlano">
        <Text style={tipo.corpo}>Situação da manutenção entra na Fase 4.</Text>
      </Card>

      <Card titulo="Financeiro">
        <Text style={tipo.corpo}>Mensalidades entram na Fase 6.</Text>
      </Card>
    </TelaColapsavel>
  )
}
