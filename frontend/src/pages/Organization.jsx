import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tabs,
  Upload,
} from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import { organization } from '../api/endpoints'

const MAX_SCHEDULE_SIZE = 20 * 1024 * 1024

function formatSize(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

export default function Organization() {
  const { message } = App.useApp()
  const [schedules, setSchedules] = useState([])
  const [teachers, setTeachers] = useState([])
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [teacherLoading, setTeacherLoading] = useState(false)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [scheduleTarget, setScheduleTarget] = useState(null)
  const [teacherOpen, setTeacherOpen] = useState(false)
  const [teacherTarget, setTeacherTarget] = useState(null)
  const [saving, setSaving] = useState(false)
  const [scheduleForm] = Form.useForm()
  const [teacherForm] = Form.useForm()

  const loadSchedules = useCallback(async () => {
    setScheduleLoading(true)
    try {
      const { data } = await organization.schedules()
      setSchedules(data)
    } finally {
      setScheduleLoading(false)
    }
  }, [])

  const loadTeachers = useCallback(async () => {
    setTeacherLoading(true)
    try {
      const { data } = await organization.teachers()
      setTeachers(data)
    } finally {
      setTeacherLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSchedules()
    loadTeachers()
  }, [loadSchedules, loadTeachers])

  const closeSchedule = () => {
    setScheduleOpen(false)
    setScheduleTarget(null)
    scheduleForm.resetFields()
  }

  const openSchedule = (schedule = null) => {
    setScheduleTarget(schedule)
    scheduleForm.setFieldsValue({ group_name: schedule?.group_name || '', file: [] })
    setScheduleOpen(true)
  }

  const saveSchedule = async (values) => {
    const file = values.file?.[0]?.originFileObj
    if (!file) {
      message.error('Выберите фото или PDF расписания')
      return
    }
    if (file.size > MAX_SCHEDULE_SIZE) {
      message.error('Размер файла не должен превышать 20 МБ')
      return
    }

    const formData = new FormData()
    formData.append('group_name', values.group_name.trim())
    formData.append('file', file)
    setSaving(true)
    try {
      await organization.uploadSchedule(formData)
      message.success(scheduleTarget ? 'Расписание группы заменено' : 'Расписание добавлено')
      closeSchedule()
      await loadSchedules()
    } finally {
      setSaving(false)
    }
  }

  const openTeacher = (teacher = null) => {
    setTeacherTarget(teacher)
    teacherForm.setFieldsValue({
      full_name: teacher?.full_name || '',
      position: teacher?.position || '',
      area: teacher?.area || '',
    })
    setTeacherOpen(true)
  }

  const closeTeacher = () => {
    setTeacherOpen(false)
    setTeacherTarget(null)
    teacherForm.resetFields()
  }

  const saveTeacher = async (values) => {
    setSaving(true)
    try {
      if (teacherTarget) {
        await organization.updateTeacher(teacherTarget.id, values)
        message.success('Данные преподавателя сохранены')
      } else {
        await organization.createTeacher(values)
        message.success('Преподаватель добавлен')
      }
      closeTeacher()
      await loadTeachers()
    } finally {
      setSaving(false)
    }
  }

  const scheduleColumns = [
    { title: 'Группа', dataIndex: 'group_name' },
    { title: 'Файл', dataIndex: 'original_filename' },
    { title: 'Размер', dataIndex: 'size_bytes', render: formatSize, width: 120 },
    {
      title: 'Обновлено',
      dataIndex: 'updated_at',
      render: (value) => dayjs(value).format('DD.MM.YYYY HH:mm'),
      width: 160,
    },
    {
      title: 'Действия',
      width: 112,
      render: (_, row) => (
        <Space size="small">
          <Button
            size="small"
            icon={<UploadOutlined />}
            title="Заменить фото расписания"
            onClick={() => openSchedule(row)}
          />
          <Popconfirm
            title="Удалить расписание этой группы?"
            okText="Удалить"
            cancelText="Отмена"
            onConfirm={async () => {
              await organization.deleteSchedule(row.id)
              message.success('Расписание удалено')
              loadSchedules()
            }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const teacherColumns = [
    { title: 'ФИО', dataIndex: 'full_name' },
    { title: 'Должность', dataIndex: 'position' },
    { title: 'Область', dataIndex: 'area' },
    {
      title: 'Действия',
      width: 112,
      render: (_, row) => (
        <Space size="small">
          <Button
            size="small"
            icon={<EditOutlined />}
            title="Редактировать"
            onClick={() => openTeacher(row)}
          />
          <Popconfirm
            title="Удалить преподавателя?"
            okText="Удалить"
            cancelText="Отмена"
            onConfirm={async () => {
              await organization.deleteTeacher(row.id)
              message.success('Преподаватель удалён')
              loadTeachers()
            }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="page-header">
        <h2>Организационная информация</h2>
        <div className="subtitle">Расписания учебных групп и сведения о преподавателях для VK</div>
      </div>

      <Tabs
        items={[
          {
            key: 'schedules',
            label: 'Расписания',
            children: (
              <Card
                size="small"
                title="Фото расписаний по группам"
                extra={
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => openSchedule()}>
                    Добавить расписание
                  </Button>
                }
              >
                <Table
                  rowKey="id"
                  size="small"
                  loading={scheduleLoading}
                  dataSource={schedules}
                  columns={scheduleColumns}
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                />
              </Card>
            ),
          },
          {
            key: 'teachers',
            label: 'Преподаватели',
            children: (
              <Card
                size="small"
                title="Преподаватели кафедры"
                extra={
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => openTeacher()}>
                    Добавить преподавателя
                  </Button>
                }
              >
                <Table
                  rowKey="id"
                  size="small"
                  loading={teacherLoading}
                  dataSource={teachers}
                  columns={teacherColumns}
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                />
              </Card>
            ),
          },
        ]}
      />

      <Modal
        title={scheduleTarget ? `Заменить расписание: ${scheduleTarget.group_name}` : 'Новое расписание'}
        open={scheduleOpen}
        onCancel={closeSchedule}
        onOk={() => scheduleForm.submit()}
        confirmLoading={saving}
        okText={scheduleTarget ? 'Заменить' : 'Загрузить'}
        cancelText="Отмена"
      >
        <Form form={scheduleForm} layout="vertical" onFinish={saveSchedule}>
          <Form.Item
            name="group_name"
            label="Учебная группа"
            rules={[{ required: true, whitespace: true, message: 'Укажите группу' }]}
          >
            <Input placeholder="А-101" disabled={!!scheduleTarget} maxLength={40} />
          </Form.Item>
          <Form.Item
            name="file"
            label="Фото или PDF расписания"
            valuePropName="fileList"
            getValueFromEvent={(event) => (Array.isArray(event) ? event : event?.fileList)}
            rules={[{ required: true, message: 'Выберите изображение' }]}
          >
            <Upload.Dragger
              beforeUpload={() => false}
              maxCount={1}
              accept=".jpg,.jpeg,.png,.webp,.pdf"
            >
              <p className="ant-upload-icon"><UploadOutlined /></p>
              <p className="ant-upload-text">Перетащите фото или PDF или нажмите для выбора</p>
              <p className="ant-upload-hint">JPEG, PNG, WebP или PDF, до 20 МБ</p>
            </Upload.Dragger>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={teacherTarget ? 'Редактировать преподавателя' : 'Новый преподаватель'}
        open={teacherOpen}
        onCancel={closeTeacher}
        onOk={() => teacherForm.submit()}
        confirmLoading={saving}
        okText="Сохранить"
        cancelText="Отмена"
      >
        <Form form={teacherForm} layout="vertical" onFinish={saveTeacher}>
          <Form.Item name="full_name" label="ФИО" rules={[{ required: true, whitespace: true }]}>
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="position" label="Должность" rules={[{ required: true, whitespace: true }]}>
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="area" label="Область" rules={[{ required: true, whitespace: true }]}>
            <Input maxLength={512} placeholder="Направление или дисциплина" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}