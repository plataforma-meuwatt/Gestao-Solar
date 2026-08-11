import { Text } from 'react-native'

import { Card } from '@/components/Card'
import { TelaColapsavel } from '@/components/TelaColapsavel'
import { tipo } from '@/theme/tokens'

export default function Financeiro() {
  return (
    <TelaColapsavel titulo="Financeiro">
      <Card>
        <Text style={tipo.corpo}>
          Mensalidades do meuWatt e do meuPlano entram na Fase 6.
        </Text>
      </Card>
    </TelaColapsavel>
  )
}
