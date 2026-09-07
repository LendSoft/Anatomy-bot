import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Slider,
  Space,
  Spin,
  Switch,
  Typography,
} from 'antd'

import { settings } from '../api/endpoints'

const SELECT_LABELS = {
  short: 'Краткий',
  balanced: 'Сбалансированный',
  detailed: 'Подробный',
  '': 'Как настроено на сервере',
  GIGACHAT_API_PERS: 'Для физических лиц (PERS)',
  GIGACHAT_API_B2B: 'Для ИП и юрлиц (B2B)',
  GIGACHAT_API_CORP: 'Корпоративный (CORP)',
  'GigaChat-2': 'GigaChat-2 — базовая, быстрее и дешевле',
  'GigaChat-2-Pro': 'GigaChat-2-Pro — точнее',
  'GigaChat-2-Max': 'GigaChat-2-Max — максимальное качество',
  ollama: 'Локальная модель (Ollama)',
  gigachat: 'GigaChat (Сбер)',
}

function SettingField({ spec }) {
  const common = {
    name: spec.key,
    label: spec.label,
    extra: spec.description || undefined,
  }

  if (spec.type === 'bool') {
    return (
      <Form.Item {...common} valuePropName="checked">
        <Switch />
      </Form.Item>
    )
  }

  if (spec.type === 'select') {
    return (
      <Form.Item {...common}>
        <Select
          options={spec.options.map((value) => ({
            value,
            label: SELECT_LABELS[value] ?? value,
          }))}
        />
      </Form.Item>
    )
  }

  if (spec.type === 'secret') {
    return (
      <Form.Item {...common}>
        <Input.Password
          autoComplete="new-password"
          placeholder={spec.placeholder || undefined}
        />
      </Form.Item>
    )
  }

  if (spec.type === 'str') {
    return (
      <Form.Item {...common}>
        <Input allowClear placeholder={spec.placeholder || undefined} />
      </Form.Item>
    )
  }

  if (spec.type === 'text') {
    return (
      <Form.Item {...common}>
        <Input.TextArea rows={6} placeholder={spec.placeholder || undefined} />
      </Form.Item>
    )
  }

  // Дробные параметры удобнее крутить ползунком: важен не точный ввод,
  // а понимание, где значение находится в допустимом диапазоне
  if (spec.type === 'float' && spec.min !== null && spec.max !== null) {
    return (
      <Form.Item {...common}>
        <Slider
          min={spec.min}
          max={spec.max}
          step={spec.step || 0.01}
          marks={{ [spec.min]: spec.min, [spec.max]: spec.max }}
          tooltip={{ open: false }}
        />
      </Form.Item>
    )
  }

  return (
    <Form.Item {...common}>
      <InputNumber
        min={spec.min ?? undefined}
        max={spec.max ?? undefined}
        step={spec.step || 1}
        style={{ width: '100%' }}
      />
    </Form.Item>
  )
}

export default function Settings() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [schema, setSchema] = useState([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await settings.get()
      setSchema(data.schema)
      form.setFieldsValue(data.values)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Порядок групп в интерфейсе: сперва подключения, которые заполняют при
  // запуске, затем то, что крутят по ходу работы
  const GROUP_ORDER = [
    'Приветствие',
    'ВКонтакте',
    'GigaChat',
    'Языковая модель',
    'Генерация',
    'Поиск',
    'Индексация',
    'Изображения',
    'Лимиты',
  ]

  const groups = useMemo(() => {
    const byGroup = {}
    for (const spec of schema) {
      ;(byGroup[spec.group] ||= []).push(spec)
    }
    const ordered = {}
    for (const name of GROUP_ORDER) {
      if (byGroup[name]) ordered[name] = byGroup[name]
    }
    for (const [name, specs] of Object.entries(byGroup)) {
      if (!ordered[name]) ordered[name] = specs
    }
    return ordered
  }, [schema])

  const onSave = async (values) => {
    setSaving(true)
    try {
      const { data } = await settings.update(values)
      form.setFieldsValue(data.values)
      message.success('Параметры сохранены и применяются к новым вопросам')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: 400 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div>
      <div className="page-header">
        <h2>Параметры бота</h2>
      </div>

      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="Порог релевантности — главная защита от выдуманных ответов"
        description={
          <span>
            Чем выше порог, тем чаще бот честно отвечает «нет в базе» вместо догадки.
          </span>
        }
      />

      <Form form={form} layout="vertical" onFinish={onSave}>
        <Row gutter={[16, 16]}>
          {Object.entries(groups).map(([group, specs]) => (
            <Col xs={24} lg={12} key={group}>
              <Card title={group} size="small" style={{ height: '100%' }}>
                {specs.map((spec) => (
                  <SettingField key={spec.key} spec={spec} />
                ))}
              </Card>
            </Col>
          ))}
        </Row>

        <Card size="small" style={{ marginTop: 16, position: 'sticky', bottom: 0 }}>
          <Space>
            <Button type="primary" htmlType="submit" loading={saving}>
              Сохранить
            </Button>
            <Button onClick={load}>Отменить изменения</Button>
            <Popconfirm
              title="Сбросить все параметры?"
              description="Вернутся значения по умолчанию."
              okText="Сбросить"
              cancelText="Отмена"
              onConfirm={async () => {
                const { data } = await settings.reset()
                form.setFieldsValue(data.values)
                message.success('Параметры сброшены')
              }}
            >
              <Button danger>Сбросить к значениям по умолчанию</Button>
            </Popconfirm>
          </Space>
        </Card>
      </Form>
    </div>
  )
}
