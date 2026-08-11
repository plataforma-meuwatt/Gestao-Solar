import { Text } from 'react-native'

import { Card } from '@/components/Card'
import { TelaColapsavel } from '@/components/TelaColapsavel'
import { tipo } from '@/theme/tokens'

export default function Usinas() {
  return (
    <TelaColapsavel titulo="Minhas usinas">
      <Card>
        <Text style={tipo.corpo}>
          A lista entra na Fase 1, por GET /api/v1/plants.
        </Text>
      </Card>
    </TelaColapsavel>
  )
}
