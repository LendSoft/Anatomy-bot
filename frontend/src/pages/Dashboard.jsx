import { useEffect, useState } from 'react'
import {
  Alert,
  Card,
  Col,
  Empty,
  List,
  Progress,
  Row,
  Segmented,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import dayjs from 'dayjs'

import { stats } from '../api/endpoints'

export default function Dashboard() {
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [daily, setDaily] = useState([])
  const [top, setTop] = useState([])
  const [unanswered, setUnanswered] = useState([])

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    Promise.all([
      stats.overview(days),
      stats.daily(days),
      stats.topQuestions(days, 10),
      stats.unanswered(days, 20),
    ])
      .then(([o, d, t, u]) => {
        if (cancelled) return
        setOverview(o.data)
        setDaily(
          d.data.map((row) => ({ ...row, label: dayjs(row.date).format('DD.MM') })),
        )
        setTop(t.data)
        setUnanswered(u.data)
      })
      .finally(() => !cancelled && setLoading(false))

    return () => {
      cancelled = true
    }
  }, [days])

  if (loading && !overview) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: 400 }}>
        <Spin size="large" />
      </div>
    )
  }

  const refusalPercent = Math.round((overview?.refusal_rate || 0) * 100)

  return (
    <div>
      <div
        className="page-header"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}
      >
        <div>
          <h2>Дашборд</h2>
          <div className="subtitle">Работа бота и состояние базы знаний</div>
        </div>
        <Segmented
          value={days}
          onChange={setDays}
          options={[
            { label: '7 дней', value: 7 },
            { label: '30 дней', value: 30 },
            { label: '90 дней', value: 90 },
          ]}
        />
      </div>

      {overview?.documents_failed > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`Не удалось проиндексировать документов: ${overview.documents_failed}`}
          description="Откройте раздел «Материалы» — там указана причина по каждому файлу."
        />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="Вопросов за период" value={overview?.questions || 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="Отвечено"
              value={overview?.answered || 0}
              valueStyle={{ color: '#389e0d' }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="Отказов «нет в базе»"
              value={refusalPercent}
              suffix="%"
              valueStyle={{ color: refusalPercent > 30 ? '#d4380d' : '#8c8c8c' }}
            />
            <div className="stat-hint">
              {overview?.refused || 0} из {overview?.questions || 0}
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="Время ответа, медиана"
              value={overview?.avg_latency_ms || 0}
              suffix="мс"
            />
            <div className="stat-hint">95-й перцентиль: {overview?.p95_latency_ms || 0} мс</div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={16}>
          <Card title="Активность по дням" size="small">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="answered"
                  name="Отвечено"
                  stroke="#1a6fb5"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="refused"
                  name="Отказы"
                  stroke="#faad14"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="errors"
                  name="Ошибки"
                  stroke="#d4380d"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="База знаний" size="small">
            <Row gutter={[8, 16]}>
              <Col span={12}>
                <Statistic title="Документов" value={overview?.documents || 0} />
                <div className="stat-hint">
                  готово: {overview?.documents_ready || 0}
                </div>
              </Col>
              <Col span={12}>
                <Statistic title="Фрагментов" value={overview?.chunks || 0} />
                <div className="stat-hint">страниц: {overview?.pages || 0}</div>
              </Col>
              <Col span={12}>
                <Statistic title="Изображений" value={overview?.images_total || 0} />
                <div className="stat-hint">
                  в поиске: {overview?.images_indexed || 0}
                </div>
              </Col>
              <Col span={12}>
                <Statistic title="Пользователей в VK" value={overview?.vk_users_total || 0} />
                <div className="stat-hint">
                  активны: {overview?.vk_users_active || 0}
                </div>
              </Col>
            </Row>

            <div style={{ marginTop: 16 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Средняя релевантность найденного
              </Typography.Text>
              <Progress
                percent={Math.round((overview?.avg_top_score || 0) * 100)}
                size="small"
                status={overview?.avg_top_score > 0.6 ? 'success' : 'normal'}
              />
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="Частые вопросы" size="small">
            {top.length ? (
              <Table
                size="small"
                pagination={false}
                dataSource={top.map((row, i) => ({ ...row, key: i }))}
                columns={[
                  { title: 'Вопрос', dataIndex: 'question', ellipsis: true },
                  { title: 'Раз', dataIndex: 'count', width: 70, align: 'right' },
                ]}
              />
            ) : (
              <Empty description="Повторяющихся вопросов пока нет" />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card
            title="Вопросы без ответа"
            size="small"
            extra={
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                чего не хватает в базе
              </Typography.Text>
            }
          >
            {unanswered.length ? (
              <List
                size="small"
                dataSource={unanswered}
                style={{ maxHeight: 320, overflowY: 'auto' }}
                renderItem={(item) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <div style={{ fontSize: 13 }}>{item.question}</div>
                      <div className="stat-hint">
                        {dayjs(item.created_at).format('DD.MM.YYYY HH:mm')}
                        {item.top_score !== null && (
                          <Tag style={{ marginLeft: 8 }} color="orange">
                            релевантность {item.top_score.toFixed(2)}
                          </Tag>
                        )}
                      </div>
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="Все вопросы получили ответ" />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
