import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Image,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  Tooltip,
  Upload,
} from 'antd'
import { DeleteOutlined, EditOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons'

import { images } from '../api/endpoints'

const PAGE_SIZE = 24

export default function Images() {
  const { message } = App.useApp()
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadForm] = Form.useForm()
  const [editForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await images.list({
        page,
        size: PAGE_SIZE,
        search: search || undefined,
      })
      setData(data)
    } finally {
      setLoading(false)
    }
  }, [page, search])

  useEffect(() => {
    load()
  }, [load])

  const handleUpload = async (values) => {
    const file = values.file?.[0]?.originFileObj
    if (!file) {
      message.error('Выберите изображение')
      return
    }

    const formData = new FormData()
    formData.append('file', file)
    formData.append('title', values.title)
    for (const key of [
      'description',
      'structures_ru',
      'structures_lat',
      'section',
      'source_title',
      'source_authors',
      'source_page',
      'license_note',
    ]) {
      if (values[key]) formData.append(key, values[key])
    }

    setUploading(true)
    try {
      await images.upload(formData)
      message.success('Изображение загружено и отправлено на индексацию')
      setUploadOpen(false)
      uploadForm.resetFields()
      load()
    } catch {
      // перехватчик уже показал ошибку
    } finally {
      setUploading(false)
    }
  }

  const handleEdit = async (values) => {
    await images.update(editing.id, {
      ...values,
      structures_ru: values.structures_ru || null,
      structures_lat: values.structures_lat || null,
    })
    message.success('Изменения сохранены, изображение переиндексируется')
    setEditing(null)
    load()
  }

  const openEdit = (image) => {
    setEditing(image)
    editForm.setFieldsValue({
      title: image.title,
      description: image.description,
      structures_ru: image.structures_ru || [],
      structures_lat: image.structures_lat || [],
      section: image.section,
      source_title: image.source_title,
      source_authors: image.source_authors,
      source_page: image.source_page,
      license_note: image.license_note,
    })
  }

  return (
    <div>
      <div className="page-header">
        <h2>Изображения атласов</h2>
        <div className="subtitle">
          Иллюстрации, которые бот прикладывает к ответу. Поиск идёт по названию,
          перечню структур и подписи.
        </div>
      </div>

      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { display: 'flex', gap: 12, flexWrap: 'wrap' } }}
      >
        <Input.Search
          placeholder="Поиск по названию"
          allowClear
          style={{ width: 280 }}
          onSearch={(value) => {
            setSearch(value)
            setPage(1)
          }}
        />
        <Space style={{ marginLeft: 'auto' }}>
          <Tooltip title="Пересчитать векторы всех изображений">
            <Button
              icon={<ReloadOutlined />}
              onClick={async () => {
                const { data } = await images.reindexAll()
                message.success(data.detail)
              }}
            >
              Переиндексировать
            </Button>
          </Tooltip>
          <Button type="primary" onClick={() => setUploadOpen(true)}>
            Загрузить изображение
          </Button>
        </Space>
      </Card>

      {data.items.length === 0 && !loading ? (
        <Empty description="Изображений пока нет" />
      ) : (
        <Row gutter={[16, 16]}>
          {data.items.map((image) => (
            <Col xs={24} sm={12} md={8} lg={6} key={image.id}>
              <Card
                size="small"
                cover={
                  <Image
                    src={images.fileUrl(image.id, true)}
                    alt={image.title}
                    className="image-card-cover"
                    preview={{ src: images.fileUrl(image.id) }}
                  />
                }
                actions={[
                  <EditOutlined key="edit" onClick={() => openEdit(image)} />,
                  <Popconfirm
                    key="delete"
                    title="Удалить изображение?"
                    okText="Удалить"
                    cancelText="Отмена"
                    onConfirm={async () => {
                      await images.remove(image.id)
                      message.success('Изображение удалено')
                      load()
                    }}
                  >
                    <DeleteOutlined />
                  </Popconfirm>,
                ]}
              >
                <Card.Meta
                  title={
                    <Tooltip title={image.title}>
                      <span style={{ fontSize: 13 }}>{image.title}</span>
                    </Tooltip>
                  }
                  description={
                    <div>
                      {!image.is_indexed && (
                        <Tag color="orange" style={{ marginBottom: 4 }}>
                          не в поиске
                        </Tag>
                      )}
                      {image.section && <Tag>{image.section}</Tag>}
                      <div className="stat-hint" style={{ marginTop: 4 }}>
                        {image.source_title || 'источник не указан'}
                        {image.source_page ? `, с. ${image.source_page}` : ''}
                      </div>
                    </div>
                  }
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {data.total > PAGE_SIZE && (
        <Pagination
          style={{ marginTop: 24, textAlign: 'center' }}
          current={page}
          pageSize={PAGE_SIZE}
          total={data.total}
          onChange={setPage}
          showSizeChanger={false}
        />
      )}

      <Modal
        title="Загрузка изображения"
        open={uploadOpen}
        onCancel={() => !uploading && setUploadOpen(false)}
        onOk={() => uploadForm.submit()}
        confirmLoading={uploading}
        okText="Загрузить"
        cancelText="Отмена"
        width={620}
      >
        <Form form={uploadForm} layout="vertical" onFinish={handleUpload}>
          <Form.Item
            name="file"
            valuePropName="fileList"
            getValueFromEvent={(e) => (Array.isArray(e) ? e : e?.fileList)}
            rules={[{ required: true, message: 'Выберите файл' }]}
          >
            <Upload.Dragger beforeUpload={() => false} maxCount={1} accept="image/*">
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">Перетащите изображение или нажмите для выбора</p>
            </Upload.Dragger>
          </Form.Item>

          <Form.Item
            name="title"
            label="Название"
            rules={[{ required: true, message: 'Укажите название' }]}
          >
            <Input placeholder="Ветви наружной сонной артерии" />
          </Form.Item>

          <Form.Item
            name="description"
            label="Подпись"
            extra="Участвует в поиске — опишите, что изображено"
          >
            <Input.TextArea rows={2} />
          </Form.Item>

          <Form.Item
            name="structures_ru"
            label="Структуры (рус.)"
            extra="Через запятую. По ним бот подбирает картинку к ответу."
          >
            <Input placeholder="наружная сонная артерия, лицевая артерия" />
          </Form.Item>

          <Form.Item name="structures_lat" label="Структуры (лат.)">
            <Input placeholder="arteria carotis externa, arteria facialis" />
          </Form.Item>

          <Form.Item name="section" label="Раздел курса">
            <Input placeholder="Ангиология" />
          </Form.Item>

          <Space style={{ display: 'flex' }} size="middle">
            <Form.Item name="source_title" label="Источник" style={{ flex: 1 }}>
              <Input placeholder="Атлас анатомии человека" />
            </Form.Item>
            <Form.Item name="source_page" label="Страница" style={{ width: 110 }}>
              <InputNumber min={1} style={{ width: '100%' }} />
            </Form.Item>
          </Space>

          <Form.Item name="source_authors" label="Авторы источника">
            <Input placeholder="Синельников Р.Д." />
          </Form.Item>

          <Form.Item
            name="license_note"
            label="Права на использование"
            extra="Отметьте, на каком основании изображение можно использовать"
          >
            <Input placeholder="Разрешение кафедры / собственная разработка" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Изменение изображения"
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        okText="Сохранить"
        cancelText="Отмена"
        width={620}
      >
        <Form form={editForm} layout="vertical" onFinish={handleEdit}>
          <Form.Item name="title" label="Название" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="Подпись">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="structures_ru" label="Структуры (рус.)">
            <Select mode="tags" tokenSeparators={[',']} placeholder="Введите и нажмите Enter" />
          </Form.Item>
          <Form.Item name="structures_lat" label="Структуры (лат.)">
            <Select mode="tags" tokenSeparators={[',']} placeholder="Введите и нажмите Enter" />
          </Form.Item>
          <Form.Item name="section" label="Раздел курса">
            <Input />
          </Form.Item>
          <Space style={{ display: 'flex' }} size="middle">
            <Form.Item name="source_title" label="Источник" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item name="source_page" label="Страница" style={{ width: 110 }}>
              <InputNumber min={1} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item name="source_authors" label="Авторы источника">
            <Input />
          </Form.Item>
          <Form.Item name="license_note" label="Права на использование">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
