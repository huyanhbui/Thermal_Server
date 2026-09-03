// Batches LLM stream deltas so a long reply does not POST once per token.
namespace NodeAgent;

sealed class EventBatcher
{
    public const int MinChars = 48;
    public static readonly TimeSpan Window = TimeSpan.FromMilliseconds(120);

    readonly string _jobId;
    readonly string? _attemptId;
    readonly Func<string, string?, int, string, Task<int>> _post;
    readonly System.Text.StringBuilder _buf = new();
    int _seq;
    DateTime _opened = DateTime.UtcNow;
    readonly object _gate = new();

    public EventBatcher(string jobId, string? attemptId, int startSeq,
        Func<string, string?, int, string, Task<int>> post)
    {
        _jobId = jobId;
        _attemptId = attemptId;
        _seq = startSeq;
        _post = post;
    }

    public int Sequence => _seq;

    public async Task AddAsync(string delta)
    {
        if (string.IsNullOrEmpty(delta)) return;
        string? flush = null;
        lock (_gate)
        {
            if (_buf.Length == 0) _opened = DateTime.UtcNow;
            _buf.Append(delta);
            var age = DateTime.UtcNow - _opened;
            if (_buf.Length >= MinChars || age >= Window)
            {
                flush = _buf.ToString();
                _buf.Clear();
            }
        }
        if (flush is not null)
            _seq += await _post(_jobId, _attemptId, _seq, flush);
    }

    public async Task FlushAsync()
    {
        string? flush;
        lock (_gate)
        {
            flush = _buf.Length > 0 ? _buf.ToString() : null;
            _buf.Clear();
        }
        if (flush is not null)
            _seq += await _post(_jobId, _attemptId, _seq, flush);
    }
}
