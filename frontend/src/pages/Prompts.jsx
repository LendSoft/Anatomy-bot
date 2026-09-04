import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { DeleteOutlined, PlusOutlined, UndoOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import { prompts } from '../api/endpoints'

const KINDS = [
  {
    key: 'system',
    label: 'Системный промпт',
    hint:
      'Главная инструкция модели. Здесь заданы запрет отвечать вне найденных фрагментов, ' +
      'обязательная ссылка на источник и правила оформления с латинскими названиями.',
  },
  {
    key: 'reference_answers',
    label: 'Идеальные ответы',
    hint:
      'Примеры, которые модель берёт за образец. Полезно добавить и пример правильного ' +
      'отказа — так бот увереннее молчит там, где данных нет.',
  },
  {
    key: 'judge',
    label: 'Промпт судьи',
    hint: 'По нему модель оценивает ответы бота при прогоне контрольных наборов.',
  },
  {
    key: 'query_rewrite',
    label: 'Переформулировка запроса',
    hint: 'Приведение вопроса студента к поисковому виду перед обращением к базе.',
  },
]

function ExamplesEditor({ value = [], onChange }) {
  const update = (index, field, fieldValue) => {
    const next = [...value]
    next[index] = { ...next[index], [field]: fieldValue }
    onChange(next)
  }

  return (
    <div>
      <List
        dataSource={value}
        locale={{ emptyText: 'Примеров пока нет' }}
        renderItem={(item, index) => (
          <List.Item
            style={{ display: 'block', padding: '12px 0' }}
            actions={[
              <Button
                key="delete"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => onChange(value.filter((_, i) => i !== index))}
              />,
            ]}
          >
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Input
                placeholder="Вопрос студента"
                value={item.question}
                onChange={(e) => update(index, 'question', e.target.value)}
              />
              <Input.TextArea
                rows={5}
                placeholder="Эталонный ответ"
                value={item.answer}
                onChange={(e) => update(index, 'answer', e.target.value)}
              />
            </Space>
          </List.Item>
        )}
      />
      <Button
        icon={<PlusOutlined />}
        onClick={() => onChange([...value, { question: '', answer: '' }])}
        style={{ marginTop: 8 }}
      >
        Добавить пример
      </Button>
    </div>
  )
}

function PromptTab({ kind, hint }) {
  const { message } = App.useApp()
  const [versions, setVersions] = useState([])
  const [active, setActive] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    const { data } = await prompts.list({ kind })
    setVersions(data)
    const current = data.find((item) => item.is_active) || null
    setActive(current)
    form.setFieldsValue({
      content: current?.content || '',
      examples: current?.examples || [],
      comment: '',
    })
  }, [kind, form])

  useEffect(() => {
    load()
  }, [load])

  const onSave = async (values) => {
    setSaving(true)
    try {
      await prompts.create({
        kind,
        content: values.content,
        examples: kind === 'reference_answers' ? values.examples : null,
        comment: values.comment || null,
        activate: true,
      })
      message.success('Создана новая версия, она активна')
      load()
    } finally {
      setSaving(false)
    }
  }

  const restoreDefault = async () => {
    const { data } = await prompts.defaults(kind)
    form.setFieldsValue({ content: data.content, examples: data.examples || [] })
    message.info('Заводское значение подставлено в форму — сохраните, чтобы применить')
  }

  return (
    <div>
      <Alert type="info" showIcon message={hint} style={{ marginBottom: 16 }} />

      <Form form={form} layout="vertical" onFinish={onSave}>
        <Form.Item
          name="content"
          label={kind === 'reference_answers' ? 'Пояснение к примерам' : 'Текст промпта'}
          rules={[{ required: true, message: 'Заполните поле' }]}
        >
          <Input.TextArea rows={kind === 'reference_answers' ? 3 : 18} />
        </Form.Item>

        {kind === 'reference_answers' && (
          <Form.Item name="examples" label="Примеры «вопрос — идеальный ответ»">
            <ExamplesEditor />
          </Form.Item>
        )}

        <Form.Item name="comment" label="Что изменили" extra="Останется в истории версий">
          <Input placeholder="Ужесточил требование указывать латинские названия" />
        </Form.Item>

        <Space>
          <Button type="primary" htmlType="submit" loading={saving}>
            Сохранить как новую версию
          </Button>
          <Button icon={<UndoOutlined />} onClick={restoreDefault}>
            Подставить заводское
          </Button>
        </Space>
      </Form>

      <Card title="История версий" size="small" style={{ marginTop: 24 }}>
        <Table
          rowKey="id"
          size="small"
          dataSource={versions}
          pagination={false}
          columns={[
            {
              title: 'Версия',
              dataIndex: 'version',
              width: 100,
              render: (version, row) => (
                <Space>
                  <span>v{version}</span>
                  {row.is_active && <Tag color="green">активна</Tag>}
                </Space>
              ),
            },
            {
              title: 'Изменение',
              dataIndex: 'comment',
              render: (comment) => comment || <span className="stat-hint">—</span>,
            },
            { title: 'Автор', dataIndex: 'created_by', width: 180 },
            {
              title: 'Дата',
              dataIndex: 'created_at',
              width: 150,
              render: (value) => dayjs(value).format('DD.MM.YYYY HH:mm'),
            },
            {
              title: '',
              width: 190,
              render: (_, row) => (
                <Space size="small">
                  <Button
                    size="small"
                    onClick={() =>
                      Modal.info({
                        title: `Версия ${row.version}`,
                        width: 800,
                        content: (
                          <Typography.Paragraph
                            style={{ whiteSpace: 'pre-wrap', maxHeight: 480, overflowY: 'auto' }}
                          >
                            {row.content}
                          </Typography.Paragraph>
                        ),
                      })
                    }
                  >
                    Показать
                  </Button>
                  {!row.is_active && (
                    <>
                      <Button
                        size="small"
                        onClick={async () => {
                          await prompts.activate(row.id)
                          message.success(`Активирована версия ${row.version}`)
                          load()
                        }}
                      >
                        Активировать
                      </Button>
                      <Popconfirm
                        title="Удалить версию?"
                        okText="Удалить"
                        cancelText="Отмена"
                        onConfirm={async () => {
                          await prompts.remove(row.id)
                          load()
                        }}
                      >
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}

export default function Prompts() {
  return (
    <div>
      <div className="page-header">
        <h2>Промпты</h2>
        <div className="subtitle">
          Каждая правка создаёт новую версию — к прежней всегда можно вернуться
        </div>
      </div>

      <Card>
        <Tabs
          items={KINDS.map((kind) => ({
            key: kind.key,
            label: kind.label,
            children: <PromptTab kind={kind.key} hint={kind.hint} />,
          }))}
        />
      </Card>
    </div>
  )
}
