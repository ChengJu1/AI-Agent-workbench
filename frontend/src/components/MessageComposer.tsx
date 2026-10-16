// 负责消息输入和表单提交，防止空消息与操作期间的重复提交。
type Props = {
  value: string;
  disabled: boolean;
  sending: boolean;
  onChange: (value: string) => void;
  onSend: () => Promise<void>;
};

export function MessageComposer({ value, disabled, sending, onChange, onSend }: Props) {
  return (
    <form className="composer" onSubmit={(event) => {
      event.preventDefault();
      void onSend();
    }}>
      <input type="text" aria-label="输入消息" value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="输入你的消息" disabled={disabled} maxLength={50000} />
      <button type="submit" disabled={disabled || !value.trim()}>
        {sending ? "回复中..." : "发送"}
      </button>
    </form>
  );
}
