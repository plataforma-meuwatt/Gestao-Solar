import { Text } from 'react-native'

import { Card } from '@/components/Card'
import { TelaColapsavel } from '@/components/TelaColapsavel'
import { tipo } from '@/theme/tokens'

export default function Assistente() {
  return (
    <TelaColapsavel titulo="Assistente">
      <Card>
        <Text style={tipo.corpo}>
          O chat entra na Fase 7, sobre o assistente do meuPlano.
        </Text>
      </Card>
    </TelaColapsavel>
  )
}
