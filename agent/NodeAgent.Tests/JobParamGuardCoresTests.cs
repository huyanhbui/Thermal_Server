using NodeAgent;

namespace NodeAgent.Tests;

public class JobParamGuardCoresTests
{
    [Fact]
    public void Negative_cores_rejected_not_treated_as_all()
    {
        Assert.False(JobParamGuard.TryClampCores(-1, 8, out var v, out var reason));
        Assert.NotEqual(0, v);
        Assert.NotNull(reason);
        Assert.Contains("-1", reason);
    }

    [Fact]
    public void Zero_means_all_cores_valid()
    {
        Assert.True(JobParamGuard.TryClampCores(0, 8, out var v, out var reason));
        Assert.Equal(0, v);
        Assert.Null(reason);
    }

    [Fact]
    public void Too_large_clamped_to_processor_count()
    {
        Assert.False(JobParamGuard.TryClampCores(99, 4, out var v, out var reason));
        Assert.Equal(4, v);
        Assert.NotNull(reason);
    }

    [Fact]
    public void In_range_unchanged()
    {
        Assert.True(JobParamGuard.TryClampCores(2, 8, out var v, out var reason));
        Assert.Equal(2, v);
        Assert.Null(reason);
    }
}
