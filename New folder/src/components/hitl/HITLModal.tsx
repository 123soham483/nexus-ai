import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'

export interface HITLModalProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  action: 'approve' | 'reject'
  loading?: boolean
  detail?: string
}

export function HITLModal({ open, onClose, onConfirm, action, loading, detail }: HITLModalProps) {
  const isReject = action === 'reject'
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isReject ? 'Reject this action?' : 'Approve this action?'}
      description={
        isReject
          ? 'Rejecting will block the agent and fail the task. This cannot be undone.'
          : 'Approving lets the agent execute this action in its sandbox.'
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={isReject ? 'danger' : 'success'} loading={loading} onClick={onConfirm}>
            {isReject ? 'Reject action' : 'Approve action'}
          </Button>
        </>
      }
    >
      {detail && (
        <div className="flex items-start gap-2.5 rounded-lg border border-border bg-elevated/50 p-3 text-sm text-text-secondary">
          <AlertTriangle className={isReject ? 'h-4 w-4 shrink-0 text-error' : 'h-4 w-4 shrink-0 text-warning'} />
          <span>{detail}</span>
        </div>
      )}
    </Modal>
  )
}
